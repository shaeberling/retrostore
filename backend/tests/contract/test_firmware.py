import httpx

from retrostore.api_compat.firmware import MirrorFirmwareStorage
from retrostore.contract.firmware import (
    capture_firmware_with_client,
    compare_firmware_captures,
    firmware_scenarios,
)
from retrostore.firmware_mirror.model import FirmwareMirror, MappingObjectReader
from services.api_compat.app import create_representative_app
from tests.firmware_mirror.test_model import _fixture


def _capture(base_url: str):
    manifest, objects = _fixture()
    mirror = FirmwareMirror.from_dict(manifest, MappingObjectReader(objects))
    app = create_representative_app(
        {
            "TESTING": True,
            "RETROSTORE_FIRMWARE_STORAGE": MirrorFirmwareStorage(mirror),
        }
    )
    transport = httpx.WSGITransport(app=app)
    with httpx.Client(transport=transport, base_url="http://candidate.test") as client:
        return capture_firmware_with_client(base_url, client)


def test_firmware_corpus_is_read_only_and_covers_both_binary_products() -> None:
    scenarios = firmware_scenarios()

    assert len(scenarios) == 16
    assert all(item.method in {"GET", "POST"} for item in scenarios)
    assert all("/firmware" not in item.path or item.method == "GET" for item in scenarios)
    assert {item.path for item in scenarios} >= {
        "/card/1/firmware",
        "/trs-io/1/firmware",
        "/card/not-a-number/version",
        "/card/1/firmware/extra",
    }


def test_firmware_capture_hashes_binary_without_embedding_it_and_compares_exactly() -> None:
    reference = _capture("https://reference.test")
    candidate = _capture("https://candidate.test")

    binaries = [
        item
        for item in reference["observations"]
        if item["content_type"] == "application/octet-stream"
    ]
    assert len(binaries) == 2
    assert all(item["text_body"] is None for item in binaries)
    assert all(len(item["body_sha256"]) == 64 for item in binaries)
    report = compare_firmware_captures(reference, candidate)
    assert report["summary"] == {"total": 16, "matching": 16, "different": 0}

    candidate["observations"][0]["text_body"] = "drift"
    drift = compare_firmware_captures(reference, candidate)
    assert drift["summary"]["different"] == 1

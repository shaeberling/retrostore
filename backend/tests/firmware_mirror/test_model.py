import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from retrostore.firmware_mirror.model import (
    FirmwareMirror,
    MappingObjectReader,
    NormalizedFirmware,
    content_aggregate_sha256,
    load_firmware_mirror_archive,
)


def _record(product: str, revision: int, version: int, body: bytes) -> NormalizedFirmware:
    digest = hashlib.sha256(body).hexdigest()
    return NormalizedFirmware(
        id=f"{product}-{revision}-{version}",
        product=product,
        revision=revision,
        version=version,
        object_path=f"firmware/{product}/{revision}/{version}/{digest}.bin",
        size=len(body),
        sha256=digest,
    )


def _fixture() -> tuple[dict, dict[str, bytes]]:
    records = (
        _record("card", 1, 1, b"card one"),
        _record("card", 1, 2, b"card two"),
        _record("trs-io", 1, 1, b"trs one"),
    )
    objects = {
        records[0].object_path: b"card one",
        records[1].object_path: b"card two",
        records[2].object_path: b"trs one",
    }
    return (
        {
            "schema_version": 1,
            "source": {
                "project_id": "trs-80",
                "exported_at": "2026-08-08T00:00:00Z",
                "high_water_mark": "cursor",
            },
            "firmware": [record.to_dict() for record in records],
            "reconciliation": {
                "firmware_count": 3,
                "object_count": 3,
                "total_bytes": sum(map(len, objects.values())),
                "content_aggregate_sha256": content_aggregate_sha256(records),
            },
        },
        objects,
    )


def _archive(path: Path, manifest: dict, objects: dict[str, bytes], *, extra=None) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for object_path, body in objects.items():
            archive.writestr(f"objects/{object_path}", body)
        if extra is not None:
            archive.writestr(extra[0], extra[1])


def test_firmware_mirror_validates_records_objects_and_latest_version() -> None:
    manifest, objects = _fixture()

    mirror = FirmwareMirror.from_dict(manifest, MappingObjectReader(objects))

    assert mirror.source_project_id == "trs-80"
    assert [record.id for record in mirror.firmware] == [
        "card-1-1",
        "card-1-2",
        "trs-io-1-1",
    ]
    assert mirror.latest("card", 1).version == 2
    assert mirror.latest("card", 2) is None
    assert mirror.to_dict() == manifest


def test_firmware_aggregate_matches_language_neutral_framing() -> None:
    manifest, _ = _fixture()

    assert manifest["reconciliation"]["content_aggregate_sha256"] == (
        "97628f10de58fb2b1570045ac786bdac4cd9dab6fdda8865405c985e83a823f1"
    )


def test_archive_loader_rejects_tampering_and_unreferenced_objects(tmp_path: Path) -> None:
    manifest, objects = _fixture()
    valid = tmp_path / "valid.zip"
    _archive(valid, manifest, objects)
    assert len(load_firmware_mirror_archive(valid).firmware) == 3

    tampered = tmp_path / "tampered.zip"
    bad_objects = dict(objects)
    bad_objects[next(iter(bad_objects))] = b"tampered"
    _archive(tampered, manifest, bad_objects)
    with pytest.raises(ValueError, match="size mismatch|checksum mismatch"):
        load_firmware_mirror_archive(tampered)

    extra = tmp_path / "extra.zip"
    _archive(extra, manifest, objects, extra=("objects/firmware/card/orphan.bin", b"x"))
    with pytest.raises(ValueError, match="unreferenced objects"):
        load_firmware_mirror_archive(extra)


def test_mirror_rejects_noncanonical_order_identity_path_and_reconciliation() -> None:
    manifest, objects = _fixture()
    manifest["firmware"] = list(reversed(manifest["firmware"]))
    with pytest.raises(ValueError, match="canonical order"):
        FirmwareMirror.from_dict(manifest, MappingObjectReader(objects))

    manifest, objects = _fixture()
    manifest["firmware"][0]["id"] = "card-1-99"
    with pytest.raises(ValueError, match="ID does not match"):
        FirmwareMirror.from_dict(manifest, MappingObjectReader(objects))

    manifest, objects = _fixture()
    manifest["reconciliation"]["firmware_count"] = 99
    with pytest.raises(ValueError, match="firmware_count mismatch"):
        FirmwareMirror.from_dict(manifest, MappingObjectReader(objects))

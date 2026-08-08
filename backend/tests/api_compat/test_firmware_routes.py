import pytest

from retrostore.api_compat.firmware import MirrorFirmwareStorage
from retrostore.firmware_mirror.model import FirmwareMirror, MappingObjectReader
from services.api_compat.app import create_representative_app
from tests.firmware_mirror.test_model import _fixture


def _client():
    manifest, objects = _fixture()
    mirror = FirmwareMirror.from_dict(manifest, MappingObjectReader(objects))
    app = create_representative_app(
        {
            "TESTING": True,
            "RETROSTORE_FIRMWARE_STORAGE": MirrorFirmwareStorage(mirror),
        }
    )
    return app.test_client()


@pytest.mark.parametrize(
    ("path", "body"),
    (
        ("/card/1/version", b"2"),
        ("/trs-io/1/version", b"1"),
        ("/card/0/version", b"0"),
        ("/card/-1/version", b"0"),
        ("/card/+1/version", b"2"),
        ("/card/1/version/", b"2"),
    ),
)
def test_firmware_version_routes_preserve_legacy_text_contract(path, body) -> None:
    response = _client().get(path)

    assert response.status_code == 200
    assert response.data == body
    assert response.headers["Content-Type"] == "text/plain;charset=iso-8859-1"
    assert "Access-Control-Allow-Origin" not in response.headers


@pytest.mark.parametrize(
    ("path", "body"),
    (
        ("/card/1/firmware", b"card two"),
        ("/trs-io/1/firmware", b"trs one"),
    ),
)
def test_firmware_download_returns_latest_raw_bytes_with_cors(path, body) -> None:
    response = _client().get(path)

    assert response.status_code == 200
    assert response.data == body
    assert response.headers["Content-Type"] == "application/octet-stream"
    assert response.headers["Access-Control-Allow-Origin"] == "*"


@pytest.mark.parametrize(
    ("path", "body"),
    (
        ("/card/0/firmware", b"Cannot find firmware data."),
        ("/card/not-a-number/version", b"Revision is not a number: 'not-a-number'."),
        ("/card/2147483648/version", b"Revision is not a number: '2147483648'."),
        ("/card/1/unknown", b"Unknown request: 'unknown'."),
        ("/card/1/firmware/extra", b"Invalid URL format."),
        ("/card/", b"Invalid URL format."),
    ),
)
def test_firmware_errors_preserve_status_content_type_and_exact_body(path, body) -> None:
    response = _client().get(path)

    assert response.status_code == 400
    assert response.data == body
    assert response.headers["Content-Type"] == "text/plain;charset=iso-8859-1"
    assert "Access-Control-Allow-Origin" not in response.headers


def test_firmware_legacy_route_accepts_post() -> None:
    client = _client()

    assert client.post("/card/1/version").data == b"2"

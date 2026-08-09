import base64
import json

import pytest

from retrostore.admin.rpk import RpkValidationError, validate_rpk


def _image(extension: str, body: bytes) -> dict[str, str]:
    return {
        "ext": extension,
        "content": base64.b64encode(body).decode("ascii"),
    }


def _package(**app_overrides) -> bytes:
    app = {
        "id": "8c028afe-96b3-11e7-a68b-5b6133ca5f0c",
        "version": "1.2",
        "name": "Imported Game",
        "description": "A complete legacy package.",
        "author": "Jane Doe",
        "year_published": "1982",
        "categories": "GAME_ARCADE",
        "platform": "TRS-80",
        "screenshot": [_image("png", b"\x89PNG\r\n\x1a\ncontent")],
    }
    app.update(app_overrides)
    return json.dumps(
        {
            "app": app,
            "publisher": {
                "first_name": "Legacy",
                "last_name": "Publisher",
                "email": "claimed@example.test",
            },
            "trs": {
                "model": "MODEL_III",
                "image": {
                    "disk": [_image("dmk", b"disk")],
                    "cmd": _image("cmd", b"command"),
                    "cas": {"ext": None, "content": None},
                    "bas": {},
                },
            },
        },
        separators=(",", ":"),
    ).encode()


def test_valid_rpk_preserves_historical_id_and_normalizes_assets() -> None:
    result = validate_rpk(filename="C:\\fakepath\\game.rpk", body=_package())

    assert result.filename == "game.rpk"
    assert result.app_id == "8c028afe-96b3-11e7-a68b-5b6133ca5f0c"
    assert result.name == "Imported Game"
    assert result.release_year == 1982
    assert result.model == "MODEL_III"
    assert result.category == "GAME_ARCADE"
    assert result.claimed_publisher_name == "Legacy Publisher"
    assert result.claimed_publisher_email == "claimed@example.test"
    assert [(item.slot, item.upload.filename) for item in result.media] == [
        ("disk-1", "disk_0.dmk"),
        ("command", "command.cmd"),
    ]
    assert result.screenshots[0].filename == "screenshot_1.png"
    assert result.decoded_size == len(b"diskcommand\x89PNG\r\n\x1a\ncontent")
    assert len(result.package_sha256) == 64


@pytest.mark.parametrize(
    ("override", "message"),
    (
        ({"id": "not-an-id"}, "canonical UUID"),
        ({"platform": "Commodore 64"}, "must be TRS-80"),
        ({"categories": "UNKNOWN"}, "supported category"),
        ({"year_published": "1982.0"}, "integer from 0 to 9999"),
    ),
)
def test_rpk_rejects_invalid_listing_fields(override, message) -> None:
    with pytest.raises(RpkValidationError, match=message):
        validate_rpk(filename="game.rpk", body=_package(**override))


def test_rpk_rejects_more_than_four_disks_and_invalid_base64() -> None:
    package = json.loads(_package())
    package["trs"]["image"]["disk"] = [_image("dsk", b"x")] * 5
    with pytest.raises(RpkValidationError, match="at most four"):
        validate_rpk(filename="game.rpk", body=json.dumps(package).encode())

    package["trs"]["image"]["disk"] = [{"ext": "dsk", "content": "not-base64"}]
    with pytest.raises(RpkValidationError, match="standard Base64"):
        validate_rpk(filename="game.rpk", body=json.dumps(package).encode())


def test_rpk_rejects_duplicate_fields_and_mismatched_screenshot_type() -> None:
    with pytest.raises(RpkValidationError, match="duplicate object field"):
        validate_rpk(
            filename="game.rpk",
            body=b'{"app":{},"app":{},"trs":{}}',
        )

    package = json.loads(_package())
    package["app"]["screenshot"] = [_image("jpg", b"\x89PNG\r\n\x1a\ncontent")]
    with pytest.raises(RpkValidationError, match="does not match"):
        validate_rpk(filename="game.rpk", body=json.dumps(package).encode())


def test_optional_legacy_media_must_be_fully_present_or_fully_absent() -> None:
    package = json.loads(_package())
    package["trs"]["image"]["cas"] = {"ext": "cas", "content": ""}

    with pytest.raises(RpkValidationError, match="content is required"):
        validate_rpk(filename="game.rpk", body=json.dumps(package).encode())

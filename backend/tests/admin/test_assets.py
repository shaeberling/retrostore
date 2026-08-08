import pytest

from retrostore.admin.assets import (
    FIRMWARE_MAX_BYTES,
    MEDIA_MAX_BYTES,
    StagingAssetValidationError,
    validate_firmware_upload,
    validate_media_slot,
    validate_media_upload,
    validate_screenshot_upload,
)


def test_media_upload_normalizes_untrusted_filename_and_hashes_content() -> None:
    upload = validate_media_upload(
        filename="C:\\fakepath\\game.dmk",
        body=b"disk image",
        description="  Boot disk  ",
    )

    assert upload.filename == "game.dmk"
    assert upload.description == "Boot disk"
    assert upload.content_type == "application/octet-stream"
    assert upload.size == 10
    assert upload.sha256 == (
        "0bb2f0f3ed953c47d835a7adaefd95afa328e30a5c80fdce417dd12b014ad602"
    )


def test_upload_bounds_and_media_slots_are_enforced() -> None:
    with pytest.raises(StagingAssetValidationError, match="empty"):
        validate_media_upload(filename="disk.dmk", body=b"", description="")
    with pytest.raises(StagingAssetValidationError, match="16 MiB"):
        validate_media_upload(
            filename="disk.dmk",
            body=b"x" * (MEDIA_MAX_BYTES + 1),
            description="",
        )
    with pytest.raises(StagingAssetValidationError, match="filename"):
        validate_media_upload(filename="../", body=b"x", description="")
    with pytest.raises(StagingAssetValidationError, match="supported media slot"):
        validate_media_slot("disk-5")
    assert validate_media_slot("disk-4") == ("DISK", 3)
    assert validate_media_slot("command") == ("COMMAND", None)


@pytest.mark.parametrize(
    ("body", "content_type", "extension"),
    (
        (b"\x89PNG\r\n\x1a\ncontent", "image/png", "png"),
        (b"\xff\xd8\xffcontent\xff\xd9", "image/jpeg", "jpg"),
        (b"GIF89a-content", "image/gif", "gif"),
        (b"RIFF\x00\x00\x00\x00WEBPcontent", "image/webp", "webp"),
    ),
)
def test_screenshot_type_is_detected_from_bytes(body, content_type, extension) -> None:
    upload = validate_screenshot_upload(filename="untrusted.bin", body=body)

    assert upload.content_type == content_type
    assert upload.extension == extension


def test_screenshot_rejects_extension_only_and_unsafe_formats() -> None:
    with pytest.raises(StagingAssetValidationError, match="valid PNG"):
        validate_screenshot_upload(filename="fake.png", body=b"not an image")
    with pytest.raises(StagingAssetValidationError, match="valid PNG"):
        validate_screenshot_upload(
            filename="active.svg", body=b"<svg><script>alert(1)</script></svg>"
        )


def test_firmware_upload_is_bounded_binary_with_a_safe_name() -> None:
    upload = validate_firmware_upload(
        filename="C:\\fakepath\\card-v10.bin", body=b"firmware"
    )

    assert upload.filename == "card-v10.bin"
    assert upload.content_type == "application/octet-stream"
    assert upload.extension == "bin"
    assert upload.description == ""
    with pytest.raises(StagingAssetValidationError, match="empty"):
        validate_firmware_upload(filename="firmware.bin", body=b"")
    with pytest.raises(StagingAssetValidationError, match="4 MiB"):
        validate_firmware_upload(
            filename="firmware.bin", body=b"x" * (FIRMWARE_MAX_BYTES + 1)
        )

"""Validated immutable object storage for application assets."""

import hashlib
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from google.api_core.exceptions import NotFound, PreconditionFailed
from google.cloud import storage

MEDIA_MAX_BYTES = 16 * 1024 * 1024
SCREENSHOT_MAX_BYTES = 5 * 1024 * 1024
MEDIA_SLOTS: Mapping[str, tuple[str, int | None]] = {
    "disk-1": ("DISK", 0),
    "disk-2": ("DISK", 1),
    "disk-3": ("DISK", 2),
    "disk-4": ("DISK", 3),
    "cassette": ("CASSETTE", None),
    "command": ("COMMAND", None),
    "basic": ("BASIC", None),
}

_SCREENSHOT_FORMATS = (
    ("image/png", "png", lambda body: body.startswith(b"\x89PNG\r\n\x1a\n")),
    (
        "image/jpeg",
        "jpg",
        lambda body: body.startswith(b"\xff\xd8\xff") and body.endswith(b"\xff\xd9"),
    ),
    (
        "image/gif",
        "gif",
        lambda body: body.startswith((b"GIF87a", b"GIF89a")),
    ),
    (
        "image/webp",
        "webp",
        lambda body: len(body) >= 12 and body.startswith(b"RIFF") and body[8:12] == b"WEBP",
    ),
)


class AssetValidationError(ValueError):
    """An upload is unsafe or outside the accepted bounds."""


@dataclass(frozen=True, slots=True)
class ValidatedAssetUpload:
    filename: str
    body: bytes
    content_type: str
    extension: str | None
    size: int
    sha256: str
    description: str


class AssetStore(Protocol):
    def put_verified(self, *, path: str, body: bytes, sha256: str, content_type: str) -> bool: ...

    def read(self, path: str) -> bytes: ...

    def delete(self, path: str) -> None: ...


class CloudAssetStore:
    """Create immutable objects in one private Cloud Storage bucket."""

    def __init__(self, bucket: storage.Bucket) -> None:
        self._bucket = bucket

    def put_verified(self, *, path: str, body: bytes, sha256: str, content_type: str) -> bool:
        if hashlib.sha256(body).hexdigest() != sha256:
            raise ValueError("Object body does not match its SHA-256")
        blob = self._bucket.blob(path)
        blob.metadata = {"sha256": sha256}
        try:
            blob.upload_from_string(
                body,
                content_type=content_type,
                checksum="auto",
                if_generation_match=0,
            )
            return True
        except PreconditionFailed:
            existing = self.read(path)
            if len(existing) != len(body) or hashlib.sha256(existing).hexdigest() != sha256:
                raise ValueError(f"Immutable object collision: {path}") from None
            return False

    def read(self, path: str) -> bytes:
        try:
            return bytes(self._bucket.blob(path).download_as_bytes(checksum="auto"))
        except NotFound as error:
            raise ValueError(f"Object is missing: {path}") from error

    def delete(self, path: str) -> None:
        try:
            self._bucket.blob(path).delete()
        except NotFound:
            return


def validate_media_upload(*, filename: str, body: bytes, description: str) -> ValidatedAssetUpload:
    return _validated_upload(
        filename=filename,
        body=body,
        description=description,
        maximum=MEDIA_MAX_BYTES,
        content_type="application/octet-stream",
        extension=None,
        label="Media image",
    )


def validate_screenshot_upload(*, filename: str, body: bytes) -> ValidatedAssetUpload:
    content_type = ""
    extension = ""
    for candidate_type, candidate_extension, detector in _SCREENSHOT_FORMATS:
        if detector(body):
            content_type = candidate_type
            extension = candidate_extension
            break
    if not content_type:
        raise AssetValidationError("Screenshot must be a valid PNG, JPEG, GIF, or WebP image.")
    return _validated_upload(
        filename=filename,
        body=body,
        description="",
        maximum=SCREENSHOT_MAX_BYTES,
        content_type=content_type,
        extension=extension,
        label="Screenshot",
    )


def validate_media_slot(value: str) -> tuple[str, int | None]:
    try:
        return MEDIA_SLOTS[value]
    except KeyError as error:
        raise AssetValidationError("Select a supported media slot.") from error


def _validated_upload(
    *,
    filename: str,
    body: bytes,
    description: str,
    maximum: int,
    content_type: str,
    extension: str | None,
    label: str,
) -> ValidatedAssetUpload:
    safe_filename = _safe_filename(filename)
    normalized_description = unicodedata.normalize("NFKC", description).strip()
    if len(normalized_description) > 2_000:
        raise AssetValidationError("Media description must not exceed 2000 characters.")
    if not body:
        raise AssetValidationError(f"{label} file is empty.")
    if len(body) > maximum:
        raise AssetValidationError(f"{label} must not exceed {maximum // (1024 * 1024)} MiB.")
    digest = hashlib.sha256(body).hexdigest()
    return ValidatedAssetUpload(
        filename=safe_filename,
        body=bytes(body),
        content_type=content_type,
        extension=extension,
        size=len(body),
        sha256=digest,
        description=normalized_description,
    )


def _safe_filename(value: str) -> str:
    filename = unicodedata.normalize("NFKC", value).replace("\\", "/").rsplit("/", 1)[-1]
    filename = filename.strip()
    if (
        not filename
        or filename in {".", ".."}
        or len(filename) > 255
        or any(ord(character) < 32 or ord(character) == 127 for character in filename)
    ):
        raise AssetValidationError("Upload filename is missing or invalid.")
    return filename

"""Strict, side-effect-free validation for legacy RetroStore Package files."""

import base64
import binascii
import hashlib
import json
import unicodedata
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from retrostore.admin.assets import (
    MEDIA_MAX_BYTES,
    SCREENSHOT_MAX_BYTES,
    StagingAssetValidationError,
    ValidatedAssetUpload,
    validate_media_upload,
    validate_screenshot_upload,
)

RPK_MAX_BYTES = 32 * 1024 * 1024
RPK_MAX_DECODED_BYTES = 24 * 1024 * 1024
RPK_MAX_SCREENSHOTS = 32
_MODELS = frozenset(("MODEL_I", "MODEL_III", "MODEL_4", "MODEL_4P"))
_CATEGORIES = frozenset(("GAME", "GAME_ARCADE", "OFFICE", "OS", "OTHER"))


class RpkValidationError(ValueError):
    """An RPK cannot be safely and unambiguously imported."""


@dataclass(frozen=True, slots=True)
class RpkMedia:
    slot: str
    upload: ValidatedAssetUpload


@dataclass(frozen=True, slots=True)
class ValidatedRpk:
    filename: str
    package_sha256: str
    package_size: int
    app_id: str
    name: str
    version: str
    description: str
    release_year: int
    model: str
    category: str
    author_name: str
    claimed_publisher_name: str
    claimed_publisher_email: str
    media: tuple[RpkMedia, ...]
    screenshots: tuple[ValidatedAssetUpload, ...]

    @property
    def decoded_size(self) -> int:
        return sum(item.upload.size for item in self.media) + sum(
            item.size for item in self.screenshots
        )


def validate_rpk(*, filename: str, body: bytes) -> ValidatedRpk:
    """Validate an entire package before any staged catalog mutation."""

    safe_filename = _safe_filename(filename)
    if not body:
        raise RpkValidationError("Choose a non-empty RPK file.")
    if len(body) > RPK_MAX_BYTES:
        raise RpkValidationError(
            f"RPK file must not exceed {RPK_MAX_BYTES // (1024 * 1024)} MiB."
        )
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise RpkValidationError("RPK file must be UTF-8 JSON.") from error
    try:
        value = json.loads(text, object_pairs_hook=_object_without_duplicate_keys)
    except (json.JSONDecodeError, RpkValidationError) as error:
        raise RpkValidationError(f"RPK file is not valid JSON: {error}") from error
    root = _mapping(value, "RPK")
    app = _mapping(root.get("app"), "app")
    trs = _mapping(root.get("trs"), "trs")
    image = _mapping(trs.get("image"), "trs.image")
    publisher_value = root.get("publisher", {})
    publisher = _mapping(publisher_value, "publisher")

    app_id = _canonical_uuid(_required_text(app, "id", "app.id", 64))
    name = _required_text(app, "name", "app.name", 200)
    version = _required_text(app, "version", "app.version", 64)
    description = _required_text(app, "description", "app.description", 20_000)
    author_name = " ".join(
        _required_text(app, "author", "app.author", 200).split()
    )
    platform = _required_text(app, "platform", "app.platform", 32)
    if platform != "TRS-80":
        raise RpkValidationError("app.platform must be TRS-80.")
    category = _required_text(app, "categories", "app.categories", 64)
    if category not in _CATEGORIES:
        raise RpkValidationError("app.categories is not a supported category.")
    model = _required_text(trs, "model", "trs.model", 64)
    if model not in _MODELS:
        raise RpkValidationError("trs.model is not a supported TRS-80 model.")
    release_year = _release_year(app.get("year_published"))

    disks = _optional_list(image.get("disk"), "trs.image.disk")
    if len(disks) > 4:
        raise RpkValidationError("trs.image.disk must contain at most four disks.")
    media: list[RpkMedia] = []
    for position, media_value in enumerate(disks):
        upload = _media_upload(
            media_value,
            label=f"trs.image.disk[{position}]",
            filename_stem=f"disk_{position}",
            maximum=MEDIA_MAX_BYTES,
            optional=False,
        )
        assert upload is not None
        media.append(RpkMedia(slot=f"disk-{position + 1}", upload=upload))

    for field, slot, filename_stem in (
        ("cmd", "command", "command"),
        ("cas", "cassette", "casette"),
        ("bas", "basic", "basic"),
    ):
        upload = _media_upload(
            image.get(field),
            label=f"trs.image.{field}",
            filename_stem=filename_stem,
            maximum=MEDIA_MAX_BYTES,
            optional=True,
        )
        if upload is not None:
            media.append(RpkMedia(slot=slot, upload=upload))

    screenshot_values = _optional_list(app.get("screenshot"), "app.screenshot")
    if len(screenshot_values) > RPK_MAX_SCREENSHOTS:
        raise RpkValidationError(
            f"app.screenshot must contain at most {RPK_MAX_SCREENSHOTS} images."
        )
    screenshots = tuple(
        _screenshot_upload(value, position)
        for position, value in enumerate(screenshot_values)
    )
    decoded_size = sum(item.upload.size for item in media) + sum(
        item.size for item in screenshots
    )
    if decoded_size > RPK_MAX_DECODED_BYTES:
        raise RpkValidationError(
            "Decoded RPK assets must not exceed "
            f"{RPK_MAX_DECODED_BYTES // (1024 * 1024)} MiB in total."
        )

    first_name = _optional_text(publisher, "first_name", "publisher.first_name", 200)
    last_name = _optional_text(publisher, "last_name", "publisher.last_name", 200)
    claimed_publisher_name = " ".join(
        item for item in (first_name, last_name) if item
    )
    claimed_publisher_email = _optional_text(
        publisher, "email", "publisher.email", 320
    )
    return ValidatedRpk(
        filename=safe_filename,
        package_sha256=hashlib.sha256(body).hexdigest(),
        package_size=len(body),
        app_id=app_id,
        name=name,
        version=version,
        description=description,
        release_year=release_year,
        model=model,
        category=category,
        author_name=author_name,
        claimed_publisher_name=claimed_publisher_name,
        claimed_publisher_email=claimed_publisher_email,
        media=tuple(media),
        screenshots=screenshots,
    )


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RpkValidationError(f"duplicate object field {key!r}")
        result[key] = value
    return result


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RpkValidationError(f"{label} must be a JSON object.")
    return value


def _optional_list(value: object, label: str) -> list[object]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise RpkValidationError(f"{label} must be a JSON array.")
    return value


def _required_text(
    value: Mapping[str, Any], field: str, label: str, maximum: int
) -> str:
    result = _optional_text(value, field, label, maximum)
    if not result:
        raise RpkValidationError(f"{label} is required.")
    return result


def _optional_text(
    value: Mapping[str, Any], field: str, label: str, maximum: int
) -> str:
    candidate = value.get(field)
    if candidate is None:
        return ""
    if not isinstance(candidate, str):
        raise RpkValidationError(f"{label} must be a string.")
    result = unicodedata.normalize("NFKC", candidate).strip()
    if len(result) > maximum:
        raise RpkValidationError(f"{label} must not exceed {maximum} characters.")
    return result


def _canonical_uuid(value: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except ValueError as error:
        raise RpkValidationError("app.id must be a canonical UUID.") from error
    if str(parsed) != value:
        raise RpkValidationError("app.id must be a lowercase canonical UUID.")
    return value


def _release_year(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise RpkValidationError("app.year_published must be an integer from 0 to 9999.")
    try:
        result = int(value)
    except ValueError as error:
        raise RpkValidationError(
            "app.year_published must be an integer from 0 to 9999."
        ) from error
    if str(result) != str(value).strip() or not 0 <= result <= 9999:
        raise RpkValidationError("app.year_published must be an integer from 0 to 9999.")
    return result


def _media_upload(
    value: object,
    *,
    label: str,
    filename_stem: str,
    maximum: int,
    optional: bool,
) -> ValidatedAssetUpload | None:
    if value is None and optional:
        return None
    media = _mapping(value, label)
    extension = _optional_text(media, "ext", f"{label}.ext", 16).lower()
    content = _optional_text(media, "content", f"{label}.content", RPK_MAX_BYTES * 2)
    if not extension and not content and optional:
        return None
    if not extension:
        raise RpkValidationError(f"{label}.ext is required when content is present.")
    if not extension.isascii() or not extension.isalnum():
        raise RpkValidationError(f"{label}.ext must contain only ASCII letters and digits.")
    if not content:
        raise RpkValidationError(f"{label}.content is required.")
    decoded = _decode_base64(content, label, maximum)
    try:
        return validate_media_upload(
            filename=f"{filename_stem}.{extension}", body=decoded, description=""
        )
    except StagingAssetValidationError as error:
        raise RpkValidationError(f"{label}: {error}") from error


def _screenshot_upload(value: object, position: int) -> ValidatedAssetUpload:
    label = f"app.screenshot[{position}]"
    media = _mapping(value, label)
    declared_extension = _required_text(media, "ext", f"{label}.ext", 16).lower()
    if not declared_extension.isascii() or not declared_extension.isalnum():
        raise RpkValidationError(f"{label}.ext must contain only ASCII letters and digits.")
    content = _required_text(media, "content", f"{label}.content", RPK_MAX_BYTES * 2)
    decoded = _decode_base64(content, label, SCREENSHOT_MAX_BYTES)
    try:
        detected = validate_screenshot_upload(
            filename=f"screenshot_{position + 1}.{declared_extension}", body=decoded
        )
    except StagingAssetValidationError as error:
        raise RpkValidationError(f"{label}: {error}") from error
    expected_extensions = {
        "png": "png",
        "jpg": "jpg",
        "jpeg": "jpg",
        "gif": "gif",
        "webp": "webp",
    }
    if expected_extensions.get(declared_extension) != detected.extension:
        raise RpkValidationError(
            f"{label}.ext does not match the image content ({detected.extension})."
        )
    return detected


def _decode_base64(value: str, label: str, maximum: int) -> bytes:
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError as error:
        raise RpkValidationError(f"{label}.content must be standard Base64.") from error
    if len(encoded) > ((maximum + 2) // 3) * 4:
        raise RpkValidationError(
            f"{label} decoded content must not exceed {maximum // (1024 * 1024)} MiB."
        )
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise RpkValidationError(f"{label}.content must be standard Base64.") from error
    if not decoded:
        raise RpkValidationError(f"{label}.content decodes to an empty file.")
    if len(decoded) > maximum:
        raise RpkValidationError(
            f"{label} decoded content must not exceed {maximum // (1024 * 1024)} MiB."
        )
    return decoded


def _safe_filename(value: str) -> str:
    filename = unicodedata.normalize("NFKC", value).replace("\\", "/").rsplit("/", 1)[-1]
    filename = filename.strip()
    if (
        not filename
        or filename in {".", ".."}
        or len(filename) > 255
        or any(ord(character) < 32 or ord(character) == 127 for character in filename)
    ):
        raise RpkValidationError("RPK filename is missing or invalid.")
    return filename

"""Storage-independent catalog domain models."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Self

MEDIA_TYPES = frozenset({"DISK", "CASSETTE", "COMMAND", "BASIC"})
TRS80_MODELS = frozenset({"UNKNOWN_MODEL", "MODEL_I", "MODEL_III", "MODEL_4", "MODEL_4P"})
_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class ObjectMetadata:
    path: str
    size: int
    sha256: str

    @classmethod
    def from_values(cls, value: Mapping[str, Any]) -> Self:
        path = _non_empty_string(value, "object_path")
        validate_object_path(path)
        size = _integer(value, "size")
        if size < 0:
            raise ValueError("Object size cannot be negative")
        digest = _non_empty_string(value, "sha256")
        if _SHA256.fullmatch(digest) is None:
            raise ValueError("Object sha256 must be a lowercase SHA-256 digest")
        return cls(path, size, digest)

    def to_dict(self) -> dict[str, str | int]:
        return {
            "object_path": self.path,
            "size": self.size,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class CatalogMedia:
    id: str
    app_id: str
    media_type: str
    filename: str
    description: str
    upload_time_ms: int
    object: ObjectMetadata

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        media_type = _non_empty_string(value, "media_type")
        if media_type not in MEDIA_TYPES:
            raise ValueError(f"Unsupported media type: {media_type}")
        upload_time_ms = _integer(value, "upload_time_ms")
        if upload_time_ms < 0:
            raise ValueError("Media upload_time_ms cannot be negative")
        return cls(
            id=_non_empty_string(value, "id"),
            app_id=_non_empty_string(value, "app_id"),
            media_type=media_type,
            filename=_string(value, "filename"),
            description=_string(value, "description"),
            upload_time_ms=upload_time_ms,
            object=ObjectMetadata.from_values(value),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "app_id": self.app_id,
            "media_type": self.media_type,
            "filename": self.filename,
            "description": self.description,
            "upload_time_ms": self.upload_time_ms,
            **self.object.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class CatalogScreenshot:
    id: str
    app_id: str
    filename: str
    content_type: str
    upload_time_ms: int
    legacy_serving_url: str | None
    object: ObjectMetadata

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        upload_time_ms = _integer(value, "upload_time_ms")
        if upload_time_ms < 0:
            raise ValueError("Screenshot upload_time_ms cannot be negative")
        legacy_serving_url = value.get("legacy_serving_url")
        if legacy_serving_url is not None and not isinstance(legacy_serving_url, str):
            raise ValueError("Screenshot legacy_serving_url must be a string or null")
        return cls(
            id=_non_empty_string(value, "id"),
            app_id=_non_empty_string(value, "app_id"),
            filename=_string(value, "filename"),
            content_type=_string(value, "content_type"),
            upload_time_ms=upload_time_ms,
            legacy_serving_url=legacy_serving_url,
            object=ObjectMetadata.from_values(value),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "app_id": self.app_id,
            "filename": self.filename,
            "content_type": self.content_type,
            "upload_time_ms": self.upload_time_ms,
            "legacy_serving_url": self.legacy_serving_url,
            **self.object.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class CatalogApp:
    id: str
    name: str
    version: str
    description: str
    release_year: int
    platform: str
    model: str
    categories: tuple[str, ...]
    author_id: str | None
    author_name: str
    publisher_email: str
    first_published_at_ms: int
    updated_at_ms: int
    disk_media_ids: tuple[str | None, str | None, str | None, str | None]
    cassette_media_id: str | None
    command_media_id: str | None
    basic_media_id: str | None
    screenshot_ids: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        model = _non_empty_string(value, "model")
        if model not in TRS80_MODELS:
            raise ValueError(f"Unsupported TRS-80 model: {model}")
        if _non_empty_string(value, "platform") != "TRS80":
            raise ValueError("Catalog schema 1 supports only the TRS80 platform")

        categories = _string_list(value, "categories")
        screenshot_ids = _string_list(value, "screenshot_ids", non_empty=True)
        slots = value.get("media_slots")
        if not isinstance(slots, Mapping):
            raise ValueError("App media_slots must be an object")
        if set(slots) != {"disks", "cassette", "command", "basic"}:
            raise ValueError("App media_slots must contain disks, cassette, command, and basic")
        disks = slots["disks"]
        if not isinstance(disks, list) or len(disks) != 4:
            raise ValueError("App media_slots.disks must contain exactly four positions")
        disk_ids = tuple(_optional_id(item, "disk media ID") for item in disks)

        author_id = value.get("author_id")
        if author_id is not None and not isinstance(author_id, str):
            raise ValueError("App author_id must be a string or null")
        release_year = _integer(value, "release_year")
        first_published_at_ms = _integer(value, "first_published_at_ms")
        updated_at_ms = _integer(value, "updated_at_ms")
        if min(release_year, first_published_at_ms, updated_at_ms) < 0:
            raise ValueError("App year and timestamps cannot be negative")

        return cls(
            id=_non_empty_string(value, "id"),
            name=_string(value, "name"),
            version=_string(value, "version"),
            description=_string(value, "description"),
            release_year=release_year,
            platform="TRS80",
            model=model,
            categories=categories,
            author_id=author_id,
            author_name=_string(value, "author_name"),
            publisher_email=_string(value, "publisher_email"),
            first_published_at_ms=first_published_at_ms,
            updated_at_ms=updated_at_ms,
            disk_media_ids=disk_ids,  # type: ignore[arg-type]
            cassette_media_id=_optional_id(slots["cassette"], "cassette media ID"),
            command_media_id=_optional_id(slots["command"], "command media ID"),
            basic_media_id=_optional_id(slots["basic"], "basic media ID"),
            screenshot_ids=screenshot_ids,
        )

    def media_slots(self) -> tuple[tuple[str, str | None], ...]:
        return (
            *(("DISK", media_id) for media_id in self.disk_media_ids),
            ("CASSETTE", self.cassette_media_id),
            ("COMMAND", self.command_media_id),
            ("BASIC", self.basic_media_id),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "release_year": self.release_year,
            "platform": self.platform,
            "model": self.model,
            "categories": list(self.categories),
            "author_id": self.author_id,
            "author_name": self.author_name,
            "publisher_email": self.publisher_email,
            "first_published_at_ms": self.first_published_at_ms,
            "updated_at_ms": self.updated_at_ms,
            "media_slots": {
                "disks": list(self.disk_media_ids),
                "cassette": self.cassette_media_id,
                "command": self.command_media_id,
                "basic": self.basic_media_id,
            },
            "screenshot_ids": list(self.screenshot_ids),
        }


def validate_object_path(path: str) -> None:
    parsed = PurePosixPath(path)
    if (
        "\\" in path
        or parsed.is_absolute()
        or path != parsed.as_posix()
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise ValueError(f"Object path must be normalized and relative: {path}")


def _string(value: Mapping[str, Any], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str):
        raise ValueError(f"{field} must be a string")
    return item


def _non_empty_string(value: Mapping[str, Any], field: str) -> str:
    item = _string(value, field)
    if not item:
        raise ValueError(f"{field} must not be empty")
    return item


def _integer(value: Mapping[str, Any], field: str) -> int:
    item = value.get(field)
    if not isinstance(item, int) or isinstance(item, bool):
        raise ValueError(f"{field} must be an integer")
    return item


def _string_list(
    value: Mapping[str, Any], field: str, *, non_empty: bool = False
) -> tuple[str, ...]:
    items = value.get(field)
    if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
        raise ValueError(f"{field} must be a list of strings")
    if non_empty and any(not item for item in items):
        raise ValueError(f"{field} entries must not be empty")
    return tuple(items)


def _optional_id(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string or null")
    return value

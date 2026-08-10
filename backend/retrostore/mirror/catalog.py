"""Versioned normalized catalog mirror used between Objectify and Firestore."""

import hashlib
import json
import os
import re
import struct
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Protocol, Self
from urllib.parse import quote

from retrostore.api_compat.storage import (
    CatalogEntry,
    CompatibilityStorage,
    InMemoryCompatibilityStorage,
    MediaSlot,
    StateStorage,
)
from retrostore.generated import ApiProtos_pb2 as api_pb

_SHA256 = re.compile(r"[0-9a-f]{64}")
_MAX_ARCHIVE_ENTRIES = 100_000
_MAX_MANIFEST_BYTES = 16 * 1024 * 1024
_MAX_ARCHIVE_OBJECT_BYTES = 1024 * 1024 * 1024
_MEDIA_TYPES = {
    "DISK": api_pb.DISK,
    "CASSETTE": api_pb.CASSETTE,
    "COMMAND": api_pb.COMMAND,
    "BASIC": api_pb.BASIC,
}
_MODELS = {
    "UNKNOWN_MODEL": api_pb.UNKNOWN_MODEL,
    "MODEL_I": api_pb.MODEL_I,
    "MODEL_III": api_pb.MODEL_III,
    "MODEL_4": api_pb.MODEL_4,
    "MODEL_4P": api_pb.MODEL_4P,
}


class ObjectReader(Protocol):
    """Read an immutable object by its normalized relative path."""

    def read(self, path: str) -> bytes: ...


class Identified(Protocol):
    id: str


@dataclass(frozen=True, slots=True)
class MappingObjectReader:
    """Deterministic object reader for export and emulator tests."""

    objects: Mapping[str, bytes]

    def read(self, path: str) -> bytes:
        try:
            return bytes(self.objects[path])
        except KeyError as error:
            raise ValueError(f"Mirror object is missing: {path}") from error


@dataclass(frozen=True, slots=True)
class ObjectDescriptor:
    path: str
    size: int
    sha256: str

    @classmethod
    def from_values(cls, value: Mapping[str, Any]) -> Self:
        path = _non_empty_string(value, "object_path")
        _validate_object_path(path)
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
class NormalizedMedia:
    id: str
    app_id: str
    media_type: str
    filename: str
    description: str
    upload_time_ms: int
    object: ObjectDescriptor

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        media_type = _non_empty_string(value, "media_type")
        if media_type not in _MEDIA_TYPES:
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
            object=ObjectDescriptor.from_values(value),
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
class NormalizedScreenshot:
    id: str
    app_id: str
    filename: str
    content_type: str
    upload_time_ms: int
    legacy_serving_url: str | None
    object: ObjectDescriptor

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
            object=ObjectDescriptor.from_values(value),
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
class NormalizedApp:
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
        if model not in _MODELS:
            raise ValueError(f"Unsupported TRS-80 model: {model}")
        if _non_empty_string(value, "platform") != "TRS80":
            raise ValueError("Catalog mirror schema 1 supports only the TRS80 platform")

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

    def media_slot_ids(self) -> tuple[tuple[int, str | None], ...]:
        return (
            *((api_pb.DISK, media_id) for media_id in self.disk_media_ids),
            (api_pb.CASSETTE, self.cassette_media_id),
            (api_pb.COMMAND, self.command_media_id),
            (api_pb.BASIC, self.basic_media_id),
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


@dataclass(frozen=True, slots=True)
class CatalogMirror:
    """Validated normalized metadata and checksum-verified immutable objects."""

    source_project_id: str
    exported_at: str
    high_water_mark: str
    apps: tuple[NormalizedApp, ...]
    media: Mapping[str, NormalizedMedia]
    screenshots: Mapping[str, NormalizedScreenshot]
    object_bytes: Mapping[str, bytes]

    @classmethod
    def from_dict(cls, value: object, object_reader: ObjectReader) -> Self:
        if not isinstance(value, Mapping):
            raise ValueError("Catalog mirror must be a JSON object")
        if value.get("schema_version") != 1:
            raise ValueError("Unsupported catalog mirror schema")
        source = value.get("source")
        if not isinstance(source, Mapping):
            raise ValueError("Catalog mirror source must be an object")
        apps = _unique_by_id(
            _records(value, "apps"), NormalizedApp.from_dict, "app"
        )
        media = _unique_by_id(
            _records(value, "media"), NormalizedMedia.from_dict, "media"
        )
        screenshots = _unique_by_id(
            _records(value, "screenshots"), NormalizedScreenshot.from_dict, "screenshot"
        )

        _validate_references(apps, media, screenshots)
        objects = _load_objects((*media.values(), *screenshots.values()), object_reader)
        _verify_reconciliation(value.get("reconciliation"), apps, media, screenshots, objects)
        return cls(
            source_project_id=_non_empty_string(source, "project_id"),
            exported_at=_non_empty_string(source, "exported_at"),
            high_water_mark=_non_empty_string(source, "high_water_mark"),
            apps=tuple(apps.values()),
            media=MappingProxyType(media),
            screenshots=MappingProxyType(screenshots),
            object_bytes=MappingProxyType(objects),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the canonical language-neutral manifest for cloud persistence."""

        objects = dict(self.object_bytes)
        return {
            "schema_version": 1,
            "source": {
                "project_id": self.source_project_id,
                "exported_at": self.exported_at,
                "high_water_mark": self.high_water_mark,
            },
            "apps": [app.to_dict() for app in sorted(self.apps, key=lambda item: item.id)],
            "media": [self.media[item_id].to_dict() for item_id in sorted(self.media)],
            "screenshots": [
                self.screenshots[item_id].to_dict() for item_id in sorted(self.screenshots)
            ],
            "reconciliation": {
                "app_count": len(self.apps),
                "media_count": len(self.media),
                "screenshot_count": len(self.screenshots),
                "object_count": len(objects),
                "total_bytes": sum(len(body) for body in objects.values()),
                "content_aggregate_sha256": _object_aggregate_sha256(objects),
            },
        }


def load_catalog_mirror_archive(path: Path) -> CatalogMirror:
    """Load the deterministic Java export archive and reject hidden or duplicate entries."""

    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > _MAX_ARCHIVE_ENTRIES:
            raise ValueError("Catalog mirror archive contains too many entries")
        names = [entry.filename for entry in entries]
        if len(names) != len(set(names)):
            raise ValueError("Catalog mirror archive contains duplicate entries")
        if names.count("manifest.json") != 1:
            raise ValueError("Catalog mirror archive must contain one manifest.json")

        manifest_entry = next(entry for entry in entries if entry.filename == "manifest.json")
        if manifest_entry.file_size > _MAX_MANIFEST_BYTES:
            raise ValueError("Catalog mirror manifest is too large")

        objects: dict[str, bytes] = {}
        total_object_bytes = 0
        for entry in entries:
            if entry.is_dir():
                raise ValueError("Catalog mirror archive must not contain directory entries")
            if entry.filename == "manifest.json":
                continue
            if not entry.filename.startswith("objects/"):
                raise ValueError(f"Unsupported catalog mirror archive entry: {entry.filename}")
            object_path = entry.filename.removeprefix("objects/")
            _validate_object_path(object_path)
            total_object_bytes += entry.file_size
            if total_object_bytes > _MAX_ARCHIVE_OBJECT_BYTES:
                raise ValueError("Catalog mirror archive objects exceed the import limit")
            objects[object_path] = archive.read(entry)

        try:
            manifest = json.loads(archive.read("manifest.json"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Catalog mirror manifest is not valid UTF-8 JSON") from error

    mirror = CatalogMirror.from_dict(manifest, MappingObjectReader(objects))
    extra_paths = set(objects) - set(mirror.object_bytes)
    if extra_paths:
        raise ValueError(
            f"Catalog mirror archive contains unreferenced objects: {sorted(extra_paths)}"
        )
    return mirror


def write_catalog_mirror_archive(mirror: CatalogMirror, path: Path) -> None:
    """Create a deterministic normalized archive without replacing an existing file."""

    manifest = json.dumps(
        mirror.to_dict(),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output, zipfile.ZipFile(output, "w") as archive:
        _write_archive_entry(archive, "manifest.json", manifest)
        for object_path, body in sorted(mirror.object_bytes.items()):
            _write_archive_entry(archive, f"objects/{object_path}", body)


def _write_archive_entry(archive: zipfile.ZipFile, name: str, body: bytes) -> None:
    entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    entry.compress_type = zipfile.ZIP_DEFLATED
    entry.create_system = 0
    archive.writestr(entry, body)


ScreenshotUrlResolver = Callable[[NormalizedScreenshot], str]


class MirrorCompatibilityStorage(CompatibilityStorage):
    """Serve the frozen public API from a validated normalized catalog mirror."""

    def __init__(
        self,
        mirror: CatalogMirror,
        *,
        screenshot_url: ScreenshotUrlResolver | None = None,
        state_storage: StateStorage | None = None,
    ) -> None:
        self._mirror = mirror
        self._screenshot_url = screenshot_url or _default_screenshot_url
        self._state_storage = state_storage or InMemoryCompatibilityStorage()
        self._entries = {app.id: self._catalog_entry(app) for app in mirror.apps}

    def get_catalog_entry(self, app_id: str) -> CatalogEntry | None:
        entry = self._entries.get(app_id)
        return None if entry is None else _copy_entry(entry)

    def list_catalog_entries(self) -> Sequence[CatalogEntry]:
        return tuple(_copy_entry(entry) for entry in self._entries.values())

    def search_app_ids(self, query: str) -> set[str]:
        needle = query.casefold()
        return {
            app.id
            for app in self._mirror.apps
            if needle in app.name.casefold() or needle in app.description.casefold()
        }

    def get_media_slots(self, app_id: str) -> Sequence[MediaSlot]:
        app = next((item for item in self._mirror.apps if item.id == app_id), None)
        if app is None:
            return ()
        slots = []
        for media_type, media_id in app.media_slot_ids():
            image = api_pb.MediaImage()
            if media_id is not None:
                media = self._mirror.media[media_id]
                image.type = _MEDIA_TYPES[media.media_type]
                image.filename = media.filename
                image.data = self._mirror.object_bytes[media.object.path]
                image.uploadTime = media.upload_time_ms
                image.description = media.description
            slots.append(MediaSlot(media_type, image))
        return tuple(slots)

    def save_state(self, state: api_pb.SystemState) -> int:
        return self._state_storage.save_state(state)

    def get_state(self, token: int) -> api_pb.SystemState | None:
        return self._state_storage.get_state(token)

    def _catalog_entry(self, app: NormalizedApp) -> CatalogEntry:
        proto = api_pb.App(
            id=app.id,
            name=app.name,
            version=app.version,
            description=app.description,
            release_year=app.release_year,
            author=app.author_name,
        )
        proto.ext_trs80.model = _MODELS[app.model]
        proto.screenshot_url.extend(
            self._screenshot_url(self._mirror.screenshots[screenshot_id])
            for screenshot_id in app.screenshot_ids
        )
        present_types = frozenset(
            media_type
            for media_type, media_id in app.media_slot_ids()
            if media_id is not None
        )
        return CatalogEntry(proto, present_types)


def _default_screenshot_url(screenshot: NormalizedScreenshot) -> str:
    return f"/assets/screenshots/{quote(screenshot.id, safe='')}"


def _validate_object_path(path: str) -> None:
    parsed = PurePosixPath(path)
    if "\\" in path or parsed.is_absolute() or path != parsed.as_posix() or any(
        part in {"", ".", ".."} for part in parsed.parts
    ):
        raise ValueError(f"Object path must be normalized and relative: {path}")


def _validate_references(
    apps: Mapping[str, NormalizedApp],
    media: Mapping[str, NormalizedMedia],
    screenshots: Mapping[str, NormalizedScreenshot],
) -> None:
    for app in apps.values():
        for expected_type, media_id in app.media_slot_ids():
            if media_id is None:
                continue
            item = media.get(media_id)
            if item is None:
                raise ValueError(f"App {app.id} references missing media {media_id}")
            if item.app_id != app.id:
                raise ValueError(f"Media {media_id} belongs to {item.app_id}, not {app.id}")
            if _MEDIA_TYPES[item.media_type] != expected_type:
                raise ValueError(f"Media {media_id} is in a slot with the wrong type")
        for screenshot_id in app.screenshot_ids:
            screenshot = screenshots.get(screenshot_id)
            if screenshot is None:
                raise ValueError(f"App {app.id} references missing screenshot {screenshot_id}")
            if screenshot.app_id != app.id:
                raise ValueError(
                    f"Screenshot {screenshot_id} belongs to {screenshot.app_id}, not {app.id}"
                )


def _load_objects(
    records: Sequence[NormalizedMedia | NormalizedScreenshot], object_reader: ObjectReader
) -> dict[str, bytes]:
    descriptors: dict[str, ObjectDescriptor] = {}
    for record in records:
        previous = descriptors.setdefault(record.object.path, record.object)
        if previous != record.object:
            raise ValueError(f"Conflicting metadata for object {record.object.path}")

    result = {}
    for descriptor in descriptors.values():
        body = object_reader.read(descriptor.path)
        if len(body) != descriptor.size:
            raise ValueError(f"Mirror object size mismatch: {descriptor.path}")
        if hashlib.sha256(body).hexdigest() != descriptor.sha256:
            raise ValueError(f"Mirror object checksum mismatch: {descriptor.path}")
        result[descriptor.path] = body
    return result


def _verify_reconciliation(
    value: object,
    apps: Mapping[str, NormalizedApp],
    media: Mapping[str, NormalizedMedia],
    screenshots: Mapping[str, NormalizedScreenshot],
    objects: Mapping[str, bytes],
) -> None:
    if value is None:
        return
    if not isinstance(value, Mapping):
        raise ValueError("Catalog mirror reconciliation must be an object")
    expected_keys = {
        "app_count",
        "media_count",
        "screenshot_count",
        "object_count",
        "total_bytes",
        "content_aggregate_sha256",
    }
    if set(value) != expected_keys:
        raise ValueError("Catalog mirror reconciliation has unsupported fields")

    expected_counts = {
        "app_count": len(apps),
        "media_count": len(media),
        "screenshot_count": len(screenshots),
        "object_count": len(objects),
        "total_bytes": sum(len(body) for body in objects.values()),
    }
    for field, expected in expected_counts.items():
        actual = _integer(value, field)
        if actual < 0 or actual != expected:
            raise ValueError(
                f"Catalog mirror reconciliation {field} mismatch: "
                f"expected {expected}, found {actual}"
            )

    expected_digest = _object_aggregate_sha256(objects)
    actual_digest = _non_empty_string(value, "content_aggregate_sha256")
    if _SHA256.fullmatch(actual_digest) is None:
        raise ValueError("Reconciliation aggregate must be a lowercase SHA-256 digest")
    if actual_digest != expected_digest:
        raise ValueError("Catalog mirror reconciliation aggregate checksum mismatch")


def _object_aggregate_sha256(objects: Mapping[str, bytes]) -> str:
    aggregate = hashlib.sha256()
    for path in sorted(objects):
        path_bytes = path.encode()
        body = objects[path]
        aggregate.update(struct.pack(">q", len(path_bytes)))
        aggregate.update(path_bytes)
        aggregate.update(struct.pack(">q", len(body)))
        aggregate.update(hashlib.sha256(body).digest())
    return aggregate.hexdigest()


def _records(value: Mapping[str, Any], field: str) -> list[Mapping[str, Any]]:
    records = value.get(field)
    if not isinstance(records, list) or any(not isinstance(item, Mapping) for item in records):
        raise ValueError(f"Catalog mirror {field} must be a list of objects")
    return records


def _unique_by_id[RecordT: Identified](
    values: list[Mapping[str, Any]],
    factory: Callable[[Mapping[str, Any]], RecordT],
    kind: str,
) -> dict[str, RecordT]:
    result = {}
    for value in values:
        record = factory(value)
        record_id = record.id
        if record_id in result:
            raise ValueError(f"Duplicate {kind} ID: {record_id}")
        result[record_id] = record
    return result


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


def _copy_entry(entry: CatalogEntry) -> CatalogEntry:
    app = api_pb.App()
    app.CopyFrom(entry.app)
    return CatalogEntry(app, entry.media_types)

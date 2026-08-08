"""Validated, versioned mirror of legacy RetroStore firmware."""

import hashlib
import json
import re
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Protocol, Self

_SHA256 = re.compile(r"[0-9a-f]{64}")
_PRODUCTS = frozenset({"card", "trs-io"})
_MAX_ARCHIVE_ENTRIES = 1_024
_MAX_MANIFEST_BYTES = 1024 * 1024
_MAX_ARCHIVE_OBJECT_BYTES = 64 * 1024 * 1024


class ObjectReader(Protocol):
    def read(self, path: str) -> bytes: ...


@dataclass(frozen=True, slots=True)
class MappingObjectReader:
    objects: Mapping[str, bytes]

    def read(self, path: str) -> bytes:
        try:
            return bytes(self.objects[path])
        except KeyError as error:
            raise ValueError(f"Firmware mirror object is missing: {path}") from error


@dataclass(frozen=True, slots=True)
class NormalizedFirmware:
    id: str
    product: str
    revision: int
    version: int
    object_path: str
    size: int
    sha256: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        product = _non_empty_string(value, "product")
        if product not in _PRODUCTS:
            raise ValueError(f"Unsupported firmware product: {product}")
        revision = _integer(value, "revision")
        version = _integer(value, "version")
        size = _integer(value, "size")
        if revision < 0:
            raise ValueError("Firmware revision cannot be negative")
        if version < 1:
            raise ValueError("Firmware version must be positive")
        if size < 0:
            raise ValueError("Firmware size cannot be negative")
        digest = _non_empty_string(value, "sha256")
        if _SHA256.fullmatch(digest) is None:
            raise ValueError("Firmware sha256 must be a lowercase SHA-256 digest")
        firmware_id = _non_empty_string(value, "id")
        expected_id = f"{product}-{revision}-{version}"
        if firmware_id != expected_id:
            raise ValueError(f"Firmware ID does not match its product and version: {firmware_id}")
        object_path = _non_empty_string(value, "object_path")
        _validate_object_path(object_path)
        expected_path = f"firmware/{product}/{revision}/{version}/{digest}.bin"
        if object_path != expected_path:
            raise ValueError(f"Firmware object path is not canonical: {object_path}")
        return cls(
            id=firmware_id,
            product=product,
            revision=revision,
            version=version,
            object_path=object_path,
            size=size,
            sha256=digest,
        )

    def to_dict(self) -> dict[str, str | int]:
        return {
            "id": self.id,
            "product": self.product,
            "revision": self.revision,
            "version": self.version,
            "object_path": self.object_path,
            "size": self.size,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class FirmwareMirror:
    source_project_id: str
    exported_at: str
    high_water_mark: str
    firmware: tuple[NormalizedFirmware, ...]
    object_bytes: Mapping[str, bytes]

    @classmethod
    def from_dict(cls, value: object, object_reader: ObjectReader) -> Self:
        if not isinstance(value, Mapping):
            raise ValueError("Firmware mirror must be a JSON object")
        if value.get("schema_version") != 1:
            raise ValueError("Unsupported firmware mirror schema")
        source = value.get("source")
        if not isinstance(source, Mapping):
            raise ValueError("Firmware mirror source must be an object")
        raw_records = value.get("firmware")
        if not isinstance(raw_records, list) or any(
            not isinstance(item, Mapping) for item in raw_records
        ):
            raise ValueError("Firmware mirror firmware must be a list of objects")
        records = tuple(NormalizedFirmware.from_dict(item) for item in raw_records)
        expected_order = tuple(
            sorted(records, key=lambda item: (item.product, item.revision, item.version))
        )
        if records != expected_order:
            raise ValueError("Firmware records are not in canonical order")
        ids = [record.id for record in records]
        if len(ids) != len(set(ids)):
            raise ValueError("Firmware mirror contains duplicate IDs")

        objects: dict[str, bytes] = {}
        for record in records:
            body = object_reader.read(record.object_path)
            if len(body) != record.size:
                raise ValueError(f"Firmware object size mismatch: {record.object_path}")
            if hashlib.sha256(body).hexdigest() != record.sha256:
                raise ValueError(f"Firmware object checksum mismatch: {record.object_path}")
            objects[record.object_path] = body
        _verify_reconciliation(value.get("reconciliation"), records, objects)
        return cls(
            source_project_id=_non_empty_string(source, "project_id"),
            exported_at=_non_empty_string(source, "exported_at"),
            high_water_mark=_non_empty_string(source, "high_water_mark"),
            firmware=records,
            object_bytes=MappingProxyType(objects),
        )

    def to_dict(self) -> dict[str, Any]:
        records = tuple(
            sorted(self.firmware, key=lambda item: (item.product, item.revision, item.version))
        )
        return {
            "schema_version": 1,
            "source": {
                "project_id": self.source_project_id,
                "exported_at": self.exported_at,
                "high_water_mark": self.high_water_mark,
            },
            "firmware": [record.to_dict() for record in records],
            "reconciliation": {
                "firmware_count": len(records),
                "object_count": len(self.object_bytes),
                "total_bytes": sum(len(body) for body in self.object_bytes.values()),
                "content_aggregate_sha256": content_aggregate_sha256(records),
            },
        }

    def latest(self, product: str, revision: int) -> NormalizedFirmware | None:
        matches = (
            record
            for record in self.firmware
            if record.product == product and record.revision == revision
        )
        return max(matches, key=lambda item: item.version, default=None)


def load_firmware_mirror_archive(path: Path) -> FirmwareMirror:
    """Load a deterministic Java export and reject hidden or unreferenced entries."""

    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > _MAX_ARCHIVE_ENTRIES:
            raise ValueError("Firmware mirror archive contains too many entries")
        names = [entry.filename for entry in entries]
        if len(names) != len(set(names)):
            raise ValueError("Firmware mirror archive contains duplicate entries")
        if names.count("manifest.json") != 1:
            raise ValueError("Firmware mirror archive must contain one manifest.json")
        manifest_entry = next(entry for entry in entries if entry.filename == "manifest.json")
        if manifest_entry.file_size > _MAX_MANIFEST_BYTES:
            raise ValueError("Firmware mirror manifest is too large")

        objects: dict[str, bytes] = {}
        total_object_bytes = 0
        for entry in entries:
            if entry.is_dir():
                raise ValueError("Firmware mirror archive must not contain directory entries")
            if entry.filename == "manifest.json":
                continue
            if not entry.filename.startswith("objects/"):
                raise ValueError(f"Unsupported firmware mirror archive entry: {entry.filename}")
            object_path = entry.filename.removeprefix("objects/")
            _validate_object_path(object_path)
            total_object_bytes += entry.file_size
            if total_object_bytes > _MAX_ARCHIVE_OBJECT_BYTES:
                raise ValueError("Firmware mirror archive objects exceed the import limit")
            objects[object_path] = archive.read(entry)
        try:
            manifest = json.loads(archive.read("manifest.json"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Firmware mirror manifest is not valid UTF-8 JSON") from error

    mirror = FirmwareMirror.from_dict(manifest, MappingObjectReader(objects))
    extra_paths = set(objects) - set(mirror.object_bytes)
    if extra_paths:
        raise ValueError(
            f"Firmware mirror archive contains unreferenced objects: {sorted(extra_paths)}"
        )
    return mirror


def content_aggregate_sha256(records: tuple[NormalizedFirmware, ...]) -> str:
    aggregate = hashlib.sha256()
    for record in records:
        frame = (
            f"{record.id}\0{record.object_path}\0{record.size}\0{record.sha256}\n"
        )
        aggregate.update(frame.encode())
    return aggregate.hexdigest()


def _verify_reconciliation(
    value: object,
    records: tuple[NormalizedFirmware, ...],
    objects: Mapping[str, bytes],
) -> None:
    if not isinstance(value, Mapping):
        raise ValueError("Firmware mirror reconciliation must be an object")
    expected_keys = {
        "firmware_count",
        "object_count",
        "total_bytes",
        "content_aggregate_sha256",
    }
    if set(value) != expected_keys:
        raise ValueError("Firmware mirror reconciliation has unsupported fields")
    expected = {
        "firmware_count": len(records),
        "object_count": len(objects),
        "total_bytes": sum(len(body) for body in objects.values()),
    }
    for field, expected_value in expected.items():
        actual = _integer(value, field)
        if actual != expected_value:
            raise ValueError(
                f"Firmware mirror reconciliation {field} mismatch: "
                f"expected {expected_value}, found {actual}"
            )
    digest = _non_empty_string(value, "content_aggregate_sha256")
    if _SHA256.fullmatch(digest) is None:
        raise ValueError("Firmware reconciliation aggregate must be a lowercase SHA-256")
    if digest != content_aggregate_sha256(records):
        raise ValueError("Firmware reconciliation aggregate checksum mismatch")


def _validate_object_path(path: str) -> None:
    parsed = PurePosixPath(path)
    if "\\" in path or parsed.is_absolute() or path != parsed.as_posix() or any(
        part in {"", ".", ".."} for part in parsed.parts
    ):
        raise ValueError(f"Object path must be normalized and relative: {path}")


def _non_empty_string(value: Mapping[str, Any], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{field} must be a non-empty string")
    return item


def _integer(value: Mapping[str, Any], field: str) -> int:
    item = value.get(field)
    if not isinstance(item, int) or isinstance(item, bool):
        raise ValueError(f"{field} must be an integer")
    return item

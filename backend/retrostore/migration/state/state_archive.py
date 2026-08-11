"""Validated, private transport archive for live public system states."""

import hashlib
import json
import os
import struct
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from google.protobuf.message import DecodeError

from retrostore.api.state_persistence import StateTokenRecord
from retrostore.generated import ApiProtos_pb2 as api_pb

_MIN_TOKEN = 100
_MAX_TOKEN = 999
_MAX_MANIFEST_BYTES = 1024 * 1024
_MAX_TOTAL_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ArchivedState:
    token: int
    created_at: datetime
    expires_at: datetime
    body: bytes
    sha256: str


@dataclass(frozen=True, slots=True)
class StateArchive:
    source_project_id: str
    captured_at: datetime
    states: tuple[ArchivedState, ...]
    content_aggregate_sha256: str


def write_state_archive(
    records: Sequence[tuple[StateTokenRecord, bytes]],
    *,
    source_project_id: str,
    captured_at: datetime,
    path: Path,
) -> None:
    """Write a create-only mode-0600 archive after validating every live payload."""

    captured_at = _aware_utc(captured_at)
    if not source_project_id:
        raise ValueError("State archive source project must not be empty")
    entries = tuple(
        sorted(
            (_archived_state(record, body, captured_at) for record, body in records),
            key=lambda value: value.token,
        )
    )
    if len({entry.token for entry in entries}) != len(entries):
        raise ValueError("State archive tokens must be unique")
    objects = {_archive_object_path(entry): bytes(entry.body) for entry in entries}
    reconciliation = _reconciliation(entries)
    manifest = {
        "schema_version": 1,
        "source": {
            "project_id": source_project_id,
            "captured_at": _format_time(captured_at),
        },
        "states": [
            {
                "token": entry.token,
                "created_at": _format_time(entry.created_at),
                "expires_at": _format_time(entry.expires_at),
                "object_path": _archive_object_path(entry),
                "size": len(entry.body),
                "sha256": entry.sha256,
            }
            for entry in entries
        ],
        "reconciliation": reconciliation,
    }
    manifest_body = json.dumps(
        manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output, zipfile.ZipFile(output, "w") as archive:
        _write_entry(archive, "manifest.json", manifest_body)
        for object_path, body in sorted(objects.items()):
            _write_entry(archive, f"objects/{object_path}", body)


def load_state_archive(path: Path) -> StateArchive:
    """Load a state archive and independently verify all metadata and protobuf bytes."""

    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(names) != len(set(names)):
            raise ValueError("State archive contains duplicate entries")
        if names.count("manifest.json") != 1:
            raise ValueError("State archive must contain one manifest.json")
        manifest_entry = next(entry for entry in entries if entry.filename == "manifest.json")
        if manifest_entry.file_size > _MAX_MANIFEST_BYTES:
            raise ValueError("State archive manifest is too large")
        try:
            manifest = json.loads(archive.read(manifest_entry))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("State archive manifest is not valid UTF-8 JSON") from error
        parsed = _parse_manifest(manifest, archive)
        expected_names = {
            "manifest.json",
            *(f"objects/{_archive_object_path(state)}" for state in parsed.states),
        }
        extras = set(names) - expected_names
        missing = expected_names - set(names)
        if extras or missing:
            raise ValueError("State archive object entries do not match its manifest")
        return parsed


def state_archive_evidence(value: StateArchive) -> dict[str, Any]:
    return {
        "state_count": len(value.states),
        "total_bytes": sum(len(state.body) for state in value.states),
        "content_aggregate_sha256": value.content_aggregate_sha256,
        "earliest_expiry": (
            _format_time(min(state.expires_at for state in value.states)) if value.states else None
        ),
        "latest_expiry": (
            _format_time(max(state.expires_at for state in value.states)) if value.states else None
        ),
    }


def _parse_manifest(value: object, archive: zipfile.ZipFile) -> StateArchive:
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("Unsupported state archive schema")
    source = value.get("source")
    if not isinstance(source, dict):
        raise ValueError("State archive source is malformed")
    project_id = source.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        raise ValueError("State archive project is malformed")
    captured_at = _parse_time(source.get("captured_at"), "captured_at")
    records = value.get("states")
    if not isinstance(records, list) or len(records) > _MAX_TOKEN - _MIN_TOKEN + 1:
        raise ValueError("State archive records are malformed")
    states: list[ArchivedState] = []
    total_bytes = 0
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("State archive record is malformed")
        token = _integer(record.get("token"), "token", _MIN_TOKEN, _MAX_TOKEN)
        created_at = _parse_time(record.get("created_at"), "created_at")
        expires_at = _parse_time(record.get("expires_at"), "expires_at")
        if created_at > captured_at or expires_at <= captured_at:
            raise ValueError("State archive contains a state outside its live window")
        object_path = record.get("object_path")
        digest = record.get("sha256")
        size = _integer(record.get("size"), "size", 0, _MAX_TOTAL_BYTES)
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError("State archive SHA-256 is malformed")
        expected_path = f"states/{token}/{digest}.pb"
        if object_path != expected_path:
            raise ValueError("State archive object path is malformed")
        _validate_object_path(expected_path)
        archive_name = f"objects/{expected_path}"
        try:
            object_entry = archive.getinfo(archive_name)
        except KeyError as error:
            raise ValueError("State archive payload is missing") from error
        if object_entry.is_dir() or object_entry.file_size != size:
            raise ValueError("State archive payload size metadata is inconsistent")
        if total_bytes + object_entry.file_size > _MAX_TOTAL_BYTES:
            raise ValueError("State archive payloads exceed the size limit")
        body = bytes(archive.read(object_entry))
        total_bytes += len(body)
        if len(body) != size or hashlib.sha256(body).hexdigest() != digest:
            raise ValueError("State archive payload failed checksum verification")
        _parse_state(body)
        states.append(ArchivedState(token, created_at, expires_at, body, digest))
    states.sort(key=lambda state: state.token)
    if len({state.token for state in states}) != len(states):
        raise ValueError("State archive tokens must be unique")
    reconciliation = value.get("reconciliation")
    expected = _reconciliation(tuple(states))
    if reconciliation != expected:
        raise ValueError("State archive reconciliation failed")
    return StateArchive(
        project_id,
        captured_at,
        tuple(states),
        expected["content_aggregate_sha256"],
    )


def _archived_state(record: StateTokenRecord, body: bytes, captured_at: datetime) -> ArchivedState:
    if not _MIN_TOKEN <= record.token <= _MAX_TOKEN:
        raise ValueError("State archive token is outside 100-999")
    created_at = _aware_utc(record.created_at)
    expires_at = _aware_utc(record.expires_at)
    if created_at > captured_at or expires_at <= captured_at:
        raise ValueError("State archive can contain only states live at capture time")
    if len(body) != record.payload.size:
        raise ValueError("State payload size does not match its token metadata")
    digest = hashlib.sha256(body).hexdigest()
    if digest != record.payload.sha256:
        raise ValueError("State payload checksum does not match its token metadata")
    _parse_state(body)
    return ArchivedState(record.token, created_at, expires_at, bytes(body), digest)


def _parse_state(body: bytes) -> api_pb.SystemState:
    try:
        return api_pb.SystemState.FromString(body)
    except DecodeError as error:
        raise ValueError("State archive payload is not a SystemState protobuf") from error


def _reconciliation(states: Sequence[ArchivedState]) -> dict[str, Any]:
    aggregate = hashlib.sha256()
    total_bytes = 0
    for state in sorted(states, key=lambda value: value.token):
        aggregate.update(struct.pack(">q", state.token))
        aggregate.update(struct.pack(">q", len(state.body)))
        aggregate.update(bytes.fromhex(state.sha256))
        total_bytes += len(state.body)
    return {
        "state_count": len(states),
        "total_bytes": total_bytes,
        "content_aggregate_sha256": aggregate.hexdigest(),
    }


def _archive_object_path(state: ArchivedState) -> str:
    return f"states/{state.token}/{state.sha256}.pb"


def _write_entry(archive: zipfile.ZipFile, name: str, body: bytes) -> None:
    entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    entry.compress_type = zipfile.ZIP_DEFLATED
    entry.create_system = 0
    archive.writestr(entry, body)


def _format_time(value: datetime) -> str:
    return _aware_utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_time(value: object, name: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"State archive {name} is malformed")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError(f"State archive {name} is malformed") from error
    return _aware_utc(parsed)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("State archive timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _integer(value: object, name: str, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise ValueError(f"State archive {name} is malformed")
    return value


def _validate_object_path(path: str) -> None:
    parsed = PurePosixPath(path)
    if (
        not path.startswith("states/")
        or "\\" in path
        or parsed.is_absolute()
        or path != parsed.as_posix()
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise ValueError("State archive object path is malformed")

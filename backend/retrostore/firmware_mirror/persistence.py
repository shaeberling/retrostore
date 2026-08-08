"""Atomic persistence boundary for normalized firmware mirrors."""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol

from retrostore.firmware_mirror.model import FirmwareMirror, ObjectReader
from retrostore.mirror.persistence import ImmutableObject, ImmutableObjectStore


@dataclass(frozen=True, slots=True)
class FirmwareSnapshot:
    id: str
    manifest_sha256: str
    metadata: Mapping[str, Any]
    versions: Mapping[str, Mapping[str, Any]]
    objects: tuple[ImmutableObject, ...]


@dataclass(frozen=True, slots=True)
class FirmwareImportReport:
    snapshot_id: str
    manifest_sha256: str
    firmware_count: int
    object_count: int
    object_bytes: int
    objects_created: int
    objects_reused: int


class FirmwareSnapshotStore(Protocol):
    def stage(self, snapshot: FirmwareSnapshot) -> None: ...

    def activate(self, snapshot_id: str, manifest_sha256: str) -> None: ...

    def load_active_manifest(self) -> Mapping[str, Any]: ...


def build_firmware_snapshot(mirror: FirmwareMirror) -> FirmwareSnapshot:
    manifest = mirror.to_dict()
    manifest_bytes = json.dumps(
        manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    snapshot_id = f"firmware-{manifest_sha256}"
    versions = MappingProxyType(
        {
            record.id: MappingProxyType(record.to_dict())
            for record in mirror.firmware
        }
    )
    objects = tuple(
        ImmutableObject(
            path=path,
            body=bytes(body),
            sha256=hashlib.sha256(body).hexdigest(),
            content_type="application/octet-stream",
        )
        for path, body in sorted(mirror.object_bytes.items())
    )
    metadata = MappingProxyType(
        {
            "schema_version": 1,
            "snapshot_id": snapshot_id,
            "manifest_sha256": manifest_sha256,
            "source": manifest["source"],
            "reconciliation": manifest["reconciliation"],
        }
    )
    return FirmwareSnapshot(
        id=snapshot_id,
        manifest_sha256=manifest_sha256,
        metadata=metadata,
        versions=versions,
        objects=objects,
    )


def import_firmware_mirror(
    mirror: FirmwareMirror,
    object_store: ImmutableObjectStore,
    snapshot_store: FirmwareSnapshotStore,
) -> FirmwareImportReport:
    snapshot = build_firmware_snapshot(mirror)
    objects_created = sum(object_store.put_verified(item) for item in snapshot.objects)
    snapshot_store.stage(snapshot)
    snapshot_store.activate(snapshot.id, snapshot.manifest_sha256)
    reconciliation = snapshot.metadata["reconciliation"]
    return FirmwareImportReport(
        snapshot_id=snapshot.id,
        manifest_sha256=snapshot.manifest_sha256,
        firmware_count=reconciliation["firmware_count"],
        object_count=reconciliation["object_count"],
        object_bytes=reconciliation["total_bytes"],
        objects_created=objects_created,
        objects_reused=len(snapshot.objects) - objects_created,
    )


def load_active_firmware_mirror(
    object_store: ObjectReader, snapshot_store: FirmwareSnapshotStore
) -> FirmwareMirror:
    return FirmwareMirror.from_dict(snapshot_store.load_active_manifest(), object_store)

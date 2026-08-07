"""Atomic, idempotent persistence boundary for normalized catalog mirrors."""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol

from retrostore.mirror.catalog import CatalogMirror, ObjectReader

_MEDIA_CONTENT_TYPE = "application/octet-stream"


@dataclass(frozen=True, slots=True)
class ImmutableObject:
    path: str
    body: bytes
    sha256: str
    content_type: str


@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    id: str
    manifest_sha256: str
    metadata: Mapping[str, Any]
    collections: Mapping[str, Mapping[str, Mapping[str, Any]]]
    objects: tuple[ImmutableObject, ...]


@dataclass(frozen=True, slots=True)
class CatalogImportReport:
    snapshot_id: str
    manifest_sha256: str
    app_count: int
    media_count: int
    screenshot_count: int
    object_count: int
    object_bytes: int
    objects_created: int
    objects_reused: int


class ImmutableObjectStore(ObjectReader, Protocol):
    """Create checksum-addressed objects and verify an existing collision."""

    def put_verified(self, value: ImmutableObject) -> bool:
        """Return true when created and false when identical content already exists."""


class CatalogSnapshotStore(Protocol):
    """Stage complete snapshots and atomically publish one active pointer."""

    def stage(self, snapshot: CatalogSnapshot) -> None: ...

    def activate(self, snapshot_id: str, manifest_sha256: str) -> None: ...

    def load_active_manifest(self) -> Mapping[str, Any]: ...


def build_catalog_snapshot(mirror: CatalogMirror) -> CatalogSnapshot:
    """Build deterministic Firestore documents and object writes from a verified mirror."""

    manifest = mirror.to_dict()
    manifest_bytes = json.dumps(
        manifest,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    snapshot_id = f"catalog-{manifest_sha256}"

    collections: dict[str, Mapping[str, Mapping[str, Any]]] = {}
    for collection in ("apps", "media", "screenshots"):
        documents = {}
        for document in manifest[collection]:
            document_id = document["id"]
            _validate_document_id(document_id)
            documents[document_id] = MappingProxyType(dict(document))
        collections[collection] = MappingProxyType(documents)

    content_types = {
        item.object.path: _MEDIA_CONTENT_TYPE for item in mirror.media.values()
    }
    content_types.update(
        {
            item.object.path: item.content_type or _MEDIA_CONTENT_TYPE
            for item in mirror.screenshots.values()
        }
    )
    objects = tuple(
        ImmutableObject(
            path=path,
            body=bytes(body),
            sha256=hashlib.sha256(body).hexdigest(),
            content_type=content_types[path],
        )
        for path, body in sorted(mirror.object_bytes.items())
    )
    metadata = MappingProxyType(
        {
            "schema_version": manifest["schema_version"],
            "snapshot_id": snapshot_id,
            "manifest_sha256": manifest_sha256,
            "source": manifest["source"],
            "reconciliation": manifest["reconciliation"],
        }
    )
    return CatalogSnapshot(
        id=snapshot_id,
        manifest_sha256=manifest_sha256,
        metadata=metadata,
        collections=MappingProxyType(collections),
        objects=objects,
    )


def import_catalog_mirror(
    mirror: CatalogMirror,
    object_store: ImmutableObjectStore,
    snapshot_store: CatalogSnapshotStore,
) -> CatalogImportReport:
    """Upload verified objects, stage metadata, then atomically publish the snapshot."""

    snapshot = build_catalog_snapshot(mirror)
    objects_created = 0
    for value in snapshot.objects:
        objects_created += object_store.put_verified(value)

    snapshot_store.stage(snapshot)
    snapshot_store.activate(snapshot.id, snapshot.manifest_sha256)
    reconciliation = snapshot.metadata["reconciliation"]
    return CatalogImportReport(
        snapshot_id=snapshot.id,
        manifest_sha256=snapshot.manifest_sha256,
        app_count=reconciliation["app_count"],
        media_count=reconciliation["media_count"],
        screenshot_count=reconciliation["screenshot_count"],
        object_count=reconciliation["object_count"],
        object_bytes=reconciliation["total_bytes"],
        objects_created=objects_created,
        objects_reused=len(snapshot.objects) - objects_created,
    )


def load_active_catalog_mirror(
    object_store: ImmutableObjectStore,
    snapshot_store: CatalogSnapshotStore,
) -> CatalogMirror:
    """Load the active snapshot and independently revalidate all cloud objects."""

    return CatalogMirror.from_dict(snapshot_store.load_active_manifest(), object_store)


def _validate_document_id(value: object) -> None:
    if not isinstance(value, str) or not value or "/" in value or value in {".", ".."}:
        raise ValueError("Catalog IDs must be safe Firestore document IDs")

import hashlib
from collections.abc import Mapping
from typing import Any

import pytest

from retrostore.mirror import (
    CatalogMirror,
    CatalogSnapshot,
    ImmutableObject,
    MappingObjectReader,
    build_catalog_snapshot,
    import_catalog_mirror,
    load_active_catalog_mirror,
)
from tests.mirror.test_catalog import _manifest, _reader, _reconciliation


class MemoryObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.fail_path: str | None = None

    def put_verified(self, value: ImmutableObject) -> bool:
        if value.path == self.fail_path:
            raise RuntimeError("injected object failure")
        existing = self.objects.get(value.path)
        if existing is None:
            self.objects[value.path] = bytes(value.body)
            return True
        if existing != value.body or hashlib.sha256(existing).hexdigest() != value.sha256:
            raise ValueError(f"Immutable object collision: {value.path}")
        return False

    def read(self, path: str) -> bytes:
        try:
            return self.objects[path]
        except KeyError as error:
            raise ValueError(f"Cloud object is missing: {path}") from error


class MemorySnapshotStore:
    def __init__(self) -> None:
        self.snapshots: dict[str, CatalogSnapshot] = {}
        self.active_id: str | None = None
        self.fail_stage = False

    def stage(self, snapshot: CatalogSnapshot) -> None:
        if self.fail_stage:
            raise RuntimeError("injected metadata failure")
        self.snapshots[snapshot.id] = snapshot

    def activate(self, snapshot_id: str, manifest_sha256: str) -> None:
        snapshot = self.snapshots[snapshot_id]
        if snapshot.manifest_sha256 != manifest_sha256:
            raise ValueError("Snapshot manifest digest does not match")
        self.active_id = snapshot_id

    def load_active_manifest(self) -> Mapping[str, Any]:
        if self.active_id is None:
            raise ValueError("No active catalog snapshot")
        snapshot = self.snapshots[self.active_id]
        return {
            "schema_version": snapshot.metadata["schema_version"],
            "source": snapshot.metadata["source"],
            "apps": list(snapshot.collections["apps"].values()),
            "media": list(snapshot.collections["media"].values()),
            "screenshots": list(snapshot.collections["screenshots"].values()),
            "reconciliation": snapshot.metadata["reconciliation"],
        }

    def load_snapshot_manifest(
        self, snapshot_id: str, manifest_sha256: str
    ) -> Mapping[str, Any]:
        snapshot = self.snapshots[snapshot_id]
        if snapshot.manifest_sha256 != manifest_sha256:
            raise ValueError("Snapshot manifest digest does not match")
        return {
            "schema_version": snapshot.metadata["schema_version"],
            "source": snapshot.metadata["source"],
            "apps": list(snapshot.collections["apps"].values()),
            "media": list(snapshot.collections["media"].values()),
            "screenshots": list(snapshot.collections["screenshots"].values()),
            "reconciliation": snapshot.metadata["reconciliation"],
        }


def _mirror(*, name: str = "Armored Patrol") -> CatalogMirror:
    manifest = _manifest()
    manifest["apps"][0]["name"] = name  # type: ignore[index]
    manifest["reconciliation"] = _reconciliation(dict(_reader().objects))
    return CatalogMirror.from_dict(manifest, _reader())


def test_snapshot_is_deterministic_and_round_trips_canonical_manifest() -> None:
    mirror = _mirror()

    first = build_catalog_snapshot(mirror)
    second = build_catalog_snapshot(mirror)
    reconstructed = CatalogMirror.from_dict(
        mirror.to_dict(), MappingObjectReader(mirror.object_bytes)
    )

    assert first.id == second.id
    assert first.manifest_sha256 == second.manifest_sha256
    assert first.metadata["reconciliation"] == {
        "app_count": 1,
        "media_count": 2,
        "screenshot_count": 1,
        "object_count": 3,
        "total_bytes": sum(len(body) for body in _reader().objects.values()),
        "content_aggregate_sha256": _reconciliation(dict(_reader().objects))[
            "content_aggregate_sha256"
        ],
    }
    assert reconstructed.to_dict() == mirror.to_dict()


def test_import_is_idempotent_and_publishes_only_after_staging() -> None:
    objects = MemoryObjectStore()
    snapshots = MemorySnapshotStore()

    first = import_catalog_mirror(_mirror(), objects, snapshots)
    second = import_catalog_mirror(_mirror(), objects, snapshots)
    active = load_active_catalog_mirror(objects, snapshots)

    assert first.snapshot_id == second.snapshot_id == snapshots.active_id
    assert first.objects_created == 3
    assert first.objects_reused == 0
    assert second.objects_created == 0
    assert second.objects_reused == 3
    assert active.to_dict() == _mirror().to_dict()


def test_object_or_metadata_failure_cannot_replace_active_snapshot() -> None:
    objects = MemoryObjectStore()
    snapshots = MemorySnapshotStore()
    original = import_catalog_mirror(_mirror(), objects, snapshots)

    changed = _mirror(name="Changed")
    objects.fail_path = build_catalog_snapshot(changed).objects[-1].path
    with pytest.raises(RuntimeError, match="object failure"):
        import_catalog_mirror(changed, objects, snapshots)
    assert snapshots.active_id == original.snapshot_id

    objects.fail_path = None
    snapshots.fail_stage = True
    with pytest.raises(RuntimeError, match="metadata failure"):
        import_catalog_mirror(changed, objects, snapshots)
    assert snapshots.active_id == original.snapshot_id


def test_existing_object_collision_fails_before_metadata_publication() -> None:
    mirror = _mirror()
    objects = MemoryObjectStore()
    snapshots = MemorySnapshotStore()
    first_object = build_catalog_snapshot(mirror).objects[0]
    objects.objects[first_object.path] = b"tampered"

    with pytest.raises(ValueError, match="Immutable object collision"):
        import_catalog_mirror(mirror, objects, snapshots)

    assert snapshots.active_id is None
    assert snapshots.snapshots == {}

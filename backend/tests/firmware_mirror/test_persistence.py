from dataclasses import dataclass, field

from retrostore.firmware_mirror.model import FirmwareMirror, MappingObjectReader
from retrostore.firmware_mirror.persistence import (
    build_firmware_snapshot,
    import_firmware_mirror,
    load_active_firmware_mirror,
)
from tests.firmware_mirror.test_model import _fixture


@dataclass
class FakeObjectStore:
    objects: dict[str, bytes] = field(default_factory=dict)

    def put_verified(self, value):
        created = value.path not in self.objects
        self.objects[value.path] = bytes(value.body)
        return created

    def read(self, path):
        return self.objects[path]


@dataclass
class FakeSnapshotStore:
    snapshots: dict = field(default_factory=dict)
    active: str | None = None

    def stage(self, snapshot):
        self.snapshots[snapshot.id] = snapshot

    def activate(self, snapshot_id, manifest_sha256):
        assert self.snapshots[snapshot_id].manifest_sha256 == manifest_sha256
        self.active = snapshot_id

    def load_active_manifest(self):
        snapshot = self.snapshots[self.active]
        metadata = snapshot.metadata
        return {
            "schema_version": metadata["schema_version"],
            "source": metadata["source"],
            "firmware": [dict(snapshot.versions[item]) for item in sorted(snapshot.versions)],
            "reconciliation": metadata["reconciliation"],
        }


def _mirror() -> FirmwareMirror:
    manifest, objects = _fixture()
    return FirmwareMirror.from_dict(manifest, MappingObjectReader(objects))


def test_snapshot_is_content_derived_and_keeps_firmware_separate_from_staging() -> None:
    snapshot = build_firmware_snapshot(_mirror())

    assert snapshot.id == f"firmware-{snapshot.manifest_sha256}"
    assert set(snapshot.versions) == {"card-1-1", "card-1-2", "trs-io-1-1"}
    assert all(item.path.startswith("firmware/") for item in snapshot.objects)
    assert snapshot.metadata["reconciliation"]["firmware_count"] == 3


def test_import_is_idempotent_and_active_mirror_revalidates_cloud_objects() -> None:
    mirror = _mirror()
    objects = FakeObjectStore()
    snapshots = FakeSnapshotStore()

    first = import_firmware_mirror(mirror, objects, snapshots)
    second = import_firmware_mirror(mirror, objects, snapshots)
    loaded = load_active_firmware_mirror(objects, snapshots)

    assert first.snapshot_id == second.snapshot_id == snapshots.active
    assert first.objects_created == 3
    assert first.objects_reused == 0
    assert second.objects_created == 0
    assert second.objects_reused == 3
    assert [item.id for item in loaded.firmware] == [
        "card-1-1",
        "card-1-2",
        "trs-io-1-1",
    ]

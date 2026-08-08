import pytest

from retrostore.firmware_mirror import (
    build_firmware_snapshot,
    import_firmware_mirror,
    load_active_firmware_mirror,
)
from retrostore.firmware_mirror.google_cloud import FirestoreFirmwareSnapshotStore
from retrostore.mirror.google_cloud import CloudStorageObjectStore
from tests.firmware_mirror.test_persistence import _mirror
from tests.mirror.test_google_cloud import FakeBucket, FakeFirestoreClient


def test_firestore_firmware_is_invisible_until_atomic_activation() -> None:
    client = FakeFirestoreClient()
    store = FirestoreFirmwareSnapshotStore(client)  # type: ignore[arg-type]
    snapshot = build_firmware_snapshot(_mirror())

    store.stage(snapshot)

    with pytest.raises(ValueError, match="No active"):
        store.load_active_manifest()
    root_path = ("firmwareSnapshots", snapshot.id)
    assert client.documents[root_path]["status"] == "STAGED"

    store.activate(snapshot.id, snapshot.manifest_sha256)

    assert client.documents[root_path]["status"] == "READY"
    assert client.documents[("firmwareControl", "active")] == {
        "snapshot_id": snapshot.id,
        "manifest_sha256": snapshot.manifest_sha256,
    }
    assert store.load_active_manifest() == _mirror().to_dict()


def test_activation_reconciles_firmware_documents_again() -> None:
    client = FakeFirestoreClient()
    store = FirestoreFirmwareSnapshotStore(client)  # type: ignore[arg-type]
    snapshot = build_firmware_snapshot(_mirror())
    store.stage(snapshot)
    version_path = ("firmwareSnapshots", snapshot.id, "versions", "card-1-1")
    client.documents[version_path]["version"] = 99

    with pytest.raises(ValueError, match="changed before activation"):
        store.activate(snapshot.id, snapshot.manifest_sha256)

    assert ("firmwareControl", "active") not in client.documents


def test_google_adapters_round_trip_and_revalidate_all_firmware() -> None:
    bucket = FakeBucket()
    client = FakeFirestoreClient()
    objects = CloudStorageObjectStore(bucket)  # type: ignore[arg-type]
    snapshots = FirestoreFirmwareSnapshotStore(client)  # type: ignore[arg-type]
    mirror = _mirror()

    report = import_firmware_mirror(mirror, objects, snapshots)
    loaded = load_active_firmware_mirror(objects, snapshots)

    assert report.firmware_count == 3
    assert report.object_count == 3
    assert loaded.to_dict() == mirror.to_dict()

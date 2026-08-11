from copy import deepcopy
from typing import Any

import pytest
from google.api_core.exceptions import NotFound, PreconditionFailed

from retrostore.migration.catalog_mirror import (
    build_catalog_snapshot,
    import_catalog_mirror,
    load_active_catalog_mirror,
)
from retrostore.migration.catalog_mirror.google_cloud import (
    CloudStorageObjectStore,
    FirestoreCatalogSnapshotStore,
)
from tests.migration.catalog_mirror.test_persistence import _mirror


class FakeBlob:
    def __init__(self, bucket: FakeBucket, name: str) -> None:
        self._bucket = bucket
        self.name = name
        self.metadata: dict[str, str] | None = None

    def upload_from_string(self, data: bytes, **kwargs: Any) -> None:
        self._bucket.upload_kwargs.append(kwargs)
        if self.name in self._bucket.objects:
            raise PreconditionFailed("object exists")
        self._bucket.objects[self.name] = bytes(data)

    def download_as_bytes(self, **kwargs: Any) -> bytes:
        try:
            return self._bucket.objects[self.name]
        except KeyError as error:
            raise NotFound("missing object") from error


class FakeBucket:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.upload_kwargs: list[dict[str, Any]] = []

    def blob(self, name: str) -> FakeBlob:
        return FakeBlob(self, name)


class FakeDocumentSnapshot:
    def __init__(self, path: tuple[str, ...], data: dict[str, Any] | None) -> None:
        self.id = path[-1]
        self.exists = data is not None
        self._data = deepcopy(data)

    def to_dict(self) -> dict[str, Any] | None:
        return deepcopy(self._data)


class FakeCollection:
    def __init__(self, client: FakeFirestoreClient, path: tuple[str, ...]) -> None:
        self._client = client
        self._path = path

    def document(self, document_id: str | None = None) -> FakeDocument:
        if document_id is None:
            document_id = f"audit-{self._client.next_audit_id}"
            self._client.next_audit_id += 1
        return FakeDocument(self._client, (*self._path, document_id))

    def stream(self, *, transaction=None) -> list[FakeDocumentSnapshot]:
        size = len(self._path) + 1
        return [
            FakeDocumentSnapshot(path, data)
            for path, data in self._client.documents.items()
            if len(path) == size and path[:-1] == self._path
        ]


class FakeDocument:
    def __init__(self, client: FakeFirestoreClient, path: tuple[str, ...]) -> None:
        self._client = client
        self.path = path

    def get(self, *, transaction=None) -> FakeDocumentSnapshot:
        return FakeDocumentSnapshot(self.path, self._client.documents.get(self.path))

    def set(self, data: dict[str, Any]) -> None:
        self._client.documents[self.path] = deepcopy(data)

    def collection(self, name: str) -> FakeCollection:
        return FakeCollection(self._client, (*self.path, name))


class FakeBatch:
    def __init__(self, client: FakeFirestoreClient) -> None:
        self._client = client
        self._writes: list[tuple[FakeDocument, dict[str, Any]]] = []

    def set(self, document: FakeDocument, data: dict[str, Any]) -> None:
        self._writes.append((document, deepcopy(data)))

    def commit(self) -> None:
        updated = deepcopy(self._client.documents)
        for document, data in self._writes:
            updated[document.path] = data
        self._client.documents = updated


class FakeFirestoreClient:
    def __init__(self) -> None:
        self.documents: dict[tuple[str, ...], dict[str, Any]] = {}
        self.next_audit_id = 1

    def collection(self, name: str) -> FakeCollection:
        return FakeCollection(self, (name,))

    def batch(self) -> FakeBatch:
        return FakeBatch(self)

    def transaction(self):
        return FakeTransaction(self)


class FakeTransaction:
    def __init__(self, client: FakeFirestoreClient) -> None:
        self._client = client

    def set(self, document: FakeDocument, data: dict[str, Any]) -> None:
        self._client.documents[document.path] = deepcopy(data)

    def create(self, document: FakeDocument, data: dict[str, Any]) -> None:
        if document.path in self._client.documents:
            raise RuntimeError("create collision")
        self._client.documents[document.path] = deepcopy(data)


def test_cloud_objects_are_create_only_and_verify_existing_content() -> None:
    bucket = FakeBucket()
    store = CloudStorageObjectStore(bucket)  # type: ignore[arg-type]
    value = build_catalog_snapshot(_mirror()).objects[0]

    assert store.put_verified(value) is True
    assert store.put_verified(value) is False
    assert bucket.upload_kwargs[0]["if_generation_match"] == 0
    assert bucket.upload_kwargs[0]["checksum"] == "auto"

    bucket.objects[value.path] = b"tampered"
    with pytest.raises(ValueError, match="Immutable cloud object collision"):
        store.put_verified(value)
    with pytest.raises(ValueError, match="Cloud object is missing"):
        store.read("missing")


def test_firestore_snapshot_is_invisible_until_atomic_activation() -> None:
    client = FakeFirestoreClient()
    store = FirestoreCatalogSnapshotStore(client)  # type: ignore[arg-type]
    snapshot = build_catalog_snapshot(_mirror())

    store.stage(snapshot)

    with pytest.raises(ValueError, match="No active"):
        store.load_active_manifest()
    root_path = ("catalogSnapshots", snapshot.id)
    assert client.documents[root_path]["status"] == "STAGED"

    store.activate(snapshot.id, snapshot.manifest_sha256)

    assert client.documents[root_path]["status"] == "READY"
    assert client.documents[("catalogControl", "active")] == {
        "snapshot_id": snapshot.id,
        "manifest_sha256": snapshot.manifest_sha256,
    }
    assert store.load_active_manifest() == _mirror().to_dict()


def test_firestore_activation_reconciles_staged_documents_again() -> None:
    client = FakeFirestoreClient()
    store = FirestoreCatalogSnapshotStore(client)  # type: ignore[arg-type]
    snapshot = build_catalog_snapshot(_mirror())
    store.stage(snapshot)
    app_path = ("catalogSnapshots", snapshot.id, "apps", "app-1")
    client.documents[app_path]["name"] = "Tampered"

    with pytest.raises(ValueError, match="changed before activation"):
        store.activate(snapshot.id, snapshot.manifest_sha256)

    assert ("catalogControl", "active") not in client.documents


def test_firestore_stage_reconciles_an_existing_ready_snapshot() -> None:
    client = FakeFirestoreClient()
    store = FirestoreCatalogSnapshotStore(client)  # type: ignore[arg-type]
    snapshot = build_catalog_snapshot(_mirror())
    store.stage(snapshot)
    store.activate(snapshot.id, snapshot.manifest_sha256)
    app_path = ("catalogSnapshots", snapshot.id, "apps", "app-1")
    client.documents[app_path]["name"] = "Tampered"

    with pytest.raises(ValueError, match="Ready Firestore snapshot"):
        store.stage(snapshot)


def test_firestore_loads_an_explicit_staged_snapshot_without_activation() -> None:
    client = FakeFirestoreClient()
    store = FirestoreCatalogSnapshotStore(client)  # type: ignore[arg-type]
    snapshot = build_catalog_snapshot(_mirror())
    store.stage(snapshot)

    manifest = store.load_snapshot_manifest(snapshot.id, snapshot.manifest_sha256)

    assert manifest == _mirror().to_dict()
    assert ("catalogControl", "active") not in client.documents
    with pytest.raises(ValueError, match="manifest SHA-256"):
        store.load_snapshot_manifest(snapshot.id, "bad")


def test_guarded_activation_and_rollback_are_exact_compare_and_swap(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "retrostore.migration.catalog_mirror.google_cloud.firestore.transactional",
        lambda function: function,
    )
    client = FakeFirestoreClient()
    store = FirestoreCatalogSnapshotStore(client)  # type: ignore[arg-type]
    active = build_catalog_snapshot(_mirror(name="Active"))
    candidate = build_catalog_snapshot(_mirror(name="Candidate"))
    store.stage(active)
    store.activate(active.id, active.manifest_sha256)
    store.stage(candidate)

    plan = store.validate_guarded_activation(
        operation="activate",
        candidate_snapshot_id=candidate.id,
        candidate_manifest_sha256=candidate.manifest_sha256,
        expected_active_snapshot_id=active.id,
        expected_active_manifest_sha256=active.manifest_sha256,
    )
    store.activate_guarded(
        operation=plan.operation,
        candidate_snapshot_id=plan.candidate_snapshot_id,
        candidate_manifest_sha256=plan.candidate_manifest_sha256,
        expected_active_snapshot_id=plan.expected_active_snapshot_id,
        expected_active_manifest_sha256=plan.expected_active_manifest_sha256,
        actor="migrator@example.test",
    )

    assert client.documents[("catalogControl", "active")] == {
        "snapshot_id": candidate.id,
        "manifest_sha256": candidate.manifest_sha256,
    }
    audits = [value for path, value in client.documents.items() if path[0] == "auditEvents"]
    assert len(audits) == 1
    assert audits[0]["previousSnapshotId"] == active.id

    store.activate_guarded(
        operation="rollback",
        candidate_snapshot_id=active.id,
        candidate_manifest_sha256=active.manifest_sha256,
        expected_active_snapshot_id=candidate.id,
        expected_active_manifest_sha256=candidate.manifest_sha256,
        actor="migrator@example.test",
    )
    assert client.documents[("catalogControl", "active")]["snapshot_id"] == active.id
    assert audits[0]["eventType"] == "CATALOG_SNAPSHOT_ACTIVATED"
    rollback_audits = [
        value
        for path, value in client.documents.items()
        if path[0] == "auditEvents" and value["eventType"] == "CATALOG_SNAPSHOT_ROLLED_BACK"
    ]
    assert len(rollback_audits) == 1

    with pytest.raises(ValueError, match="pointer changed"):
        store.validate_guarded_activation(
            operation="rollback",
            candidate_snapshot_id=active.id,
            candidate_manifest_sha256=active.manifest_sha256,
            expected_active_snapshot_id=candidate.id,
            expected_active_manifest_sha256=candidate.manifest_sha256,
        )


def test_guarded_rollback_requires_an_existing_ready_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(
        "retrostore.migration.catalog_mirror.google_cloud.firestore.transactional",
        lambda function: function,
    )
    client = FakeFirestoreClient()
    store = FirestoreCatalogSnapshotStore(client)  # type: ignore[arg-type]
    active = build_catalog_snapshot(_mirror(name="Active"))
    staged = build_catalog_snapshot(_mirror(name="Staged"))
    store.stage(active)
    store.activate(active.id, active.manifest_sha256)
    store.stage(staged)

    with pytest.raises(ValueError, match="invalid status"):
        store.validate_guarded_activation(
            operation="rollback",
            candidate_snapshot_id=staged.id,
            candidate_manifest_sha256=staged.manifest_sha256,
            expected_active_snapshot_id=active.id,
            expected_active_manifest_sha256=active.manifest_sha256,
        )


def test_google_adapters_round_trip_through_the_persistence_boundary() -> None:
    bucket = FakeBucket()
    client = FakeFirestoreClient()
    objects = CloudStorageObjectStore(bucket)  # type: ignore[arg-type]
    snapshots = FirestoreCatalogSnapshotStore(client)  # type: ignore[arg-type]
    mirror = _mirror()

    report = import_catalog_mirror(mirror, objects, snapshots)
    loaded = load_active_catalog_mirror(objects, snapshots)

    assert report.object_count == 3
    assert loaded.to_dict() == mirror.to_dict()

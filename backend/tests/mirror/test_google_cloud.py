from copy import deepcopy
from typing import Any

import pytest
from google.api_core.exceptions import NotFound, PreconditionFailed

from retrostore.mirror import (
    build_catalog_snapshot,
    import_catalog_mirror,
    load_active_catalog_mirror,
)
from retrostore.mirror.google_cloud import (
    CloudStorageObjectStore,
    FirestoreCatalogSnapshotStore,
)
from tests.mirror.test_persistence import _mirror


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

    def document(self, document_id: str) -> FakeDocument:
        return FakeDocument(self._client, (*self._path, document_id))

    def stream(self) -> list[FakeDocumentSnapshot]:
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

    def get(self) -> FakeDocumentSnapshot:
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

    def collection(self, name: str) -> FakeCollection:
        return FakeCollection(self, (name,))

    def batch(self) -> FakeBatch:
        return FakeBatch(self)


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

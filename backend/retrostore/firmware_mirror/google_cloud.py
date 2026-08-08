"""Google Cloud persistence for versioned firmware mirrors."""

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

from google.auth.credentials import Credentials
from google.cloud import firestore, storage

from retrostore.firmware_mirror.persistence import FirmwareSnapshot
from retrostore.mirror.google_cloud import (
    CloudStorageObjectStore,
    gcloud_impersonated_credentials,
    validate_catalog_target,
    validate_migration_identity,
)

_SNAPSHOTS_COLLECTION = "firmwareSnapshots"
_CONTROL_COLLECTION = "firmwareControl"
_ACTIVE_DOCUMENT = "active"
_VERSIONS_COLLECTION = "versions"
_FIRESTORE_BATCH_SIZE = 450


class FirestoreFirmwareSnapshotStore:
    """Stage a complete firmware set before atomically switching its pointer."""

    def __init__(self, client: firestore.Client) -> None:
        self._client = client

    def stage(self, snapshot: FirmwareSnapshot) -> None:
        root = self._snapshot_reference(snapshot.id)
        existing = root.get()
        if existing.exists:
            existing_data = _document_data(existing)
            _require_snapshot_identity(
                existing_data, snapshot.id, snapshot.manifest_sha256
            )
            if existing_data.get("status") == "READY":
                return

        metadata = _plain_mapping(snapshot.metadata)
        root.set({**metadata, "status": "STAGING"})
        collection = root.collection(_VERSIONS_COLLECTION)
        for chunk in _chunks(snapshot.versions.items(), _FIRESTORE_BATCH_SIZE):
            batch = self._client.batch()
            for document_id, document in chunk:
                batch.set(collection.document(document_id), _plain_mapping(document))
            batch.commit()

        manifest = self._load_snapshot_manifest(snapshot.id, allowed_statuses={"STAGING"})
        if _manifest_sha256(manifest) != snapshot.manifest_sha256:
            raise ValueError("Staged Firestore firmware does not match its manifest digest")
        root.set({**metadata, "status": "STAGED"})

    def activate(self, snapshot_id: str, manifest_sha256: str) -> None:
        root = self._snapshot_reference(snapshot_id)
        root_snapshot = root.get()
        if not root_snapshot.exists:
            raise ValueError("Firmware snapshot is not staged")
        root_data = _document_data(root_snapshot)
        _require_snapshot_identity(root_data, snapshot_id, manifest_sha256)
        if root_data.get("status") not in {"STAGED", "READY"}:
            raise ValueError("Firmware snapshot is not ready for activation")
        manifest = self._load_snapshot_manifest(
            snapshot_id, allowed_statuses={"STAGED", "READY"}
        )
        if _manifest_sha256(manifest) != manifest_sha256:
            raise ValueError("Firmware snapshot changed before activation")

        batch = self._client.batch()
        batch.set(root, {**root_data, "status": "READY"})
        batch.set(
            self._client.collection(_CONTROL_COLLECTION).document(_ACTIVE_DOCUMENT),
            {"snapshot_id": snapshot_id, "manifest_sha256": manifest_sha256},
        )
        batch.commit()

    def load_active_manifest(self) -> Mapping[str, Any]:
        active = (
            self._client.collection(_CONTROL_COLLECTION)
            .document(_ACTIVE_DOCUMENT)
            .get()
        )
        if not active.exists:
            raise ValueError("No active Firestore firmware snapshot")
        active_data = _document_data(active)
        snapshot_id = active_data.get("snapshot_id")
        manifest_sha256 = active_data.get("manifest_sha256")
        if not isinstance(snapshot_id, str) or not isinstance(manifest_sha256, str):
            raise ValueError("Active Firestore firmware pointer is malformed")
        manifest = self._load_snapshot_manifest(
            snapshot_id, allowed_statuses={"READY"}
        )
        if _manifest_sha256(manifest) != manifest_sha256:
            raise ValueError("Active Firestore firmware snapshot failed reconciliation")
        return manifest

    def _load_snapshot_manifest(
        self, snapshot_id: str, *, allowed_statuses: set[str]
    ) -> dict[str, Any]:
        root = self._snapshot_reference(snapshot_id)
        snapshot = root.get()
        if not snapshot.exists:
            raise ValueError("Firestore firmware snapshot metadata is missing")
        metadata = _document_data(snapshot)
        manifest_sha256 = metadata.get("manifest_sha256")
        if not isinstance(manifest_sha256, str):
            raise ValueError("Firestore firmware snapshot digest is missing")
        _require_snapshot_identity(metadata, snapshot_id, manifest_sha256)
        if metadata.get("status") not in allowed_statuses:
            raise ValueError("Firestore firmware snapshot has an invalid status")
        versions = sorted(
            root.collection(_VERSIONS_COLLECTION).stream(),
            key=lambda item: (
                _document_data(item).get("product"),
                _document_data(item).get("revision"),
                _document_data(item).get("version"),
            ),
        )
        return {
            "schema_version": metadata.get("schema_version"),
            "source": metadata.get("source"),
            "firmware": [_document_data(item) for item in versions],
            "reconciliation": metadata.get("reconciliation"),
        }

    def _snapshot_reference(self, snapshot_id: str) -> Any:
        return self._client.collection(_SNAPSHOTS_COLLECTION).document(snapshot_id)


def google_firmware_stores(
    *,
    project: str,
    database: str,
    bucket: str,
    impersonate_service_account: str | None = None,
    credentials: Credentials | None = None,
) -> tuple[CloudStorageObjectStore, FirestoreFirmwareSnapshotStore]:
    """Create firmware adapters for explicit isolated replacement resources."""

    validate_catalog_target(project=project, database=database, bucket=bucket)
    if impersonate_service_account is not None:
        if credentials is not None:
            raise ValueError("Pass credentials or impersonation, not both")
        validate_migration_identity(project, impersonate_service_account)
        credentials = gcloud_impersonated_credentials(
            project=project, service_account=impersonate_service_account
        )
    firestore_client = firestore.Client(
        project=project, database=database, credentials=credentials
    )
    storage_bucket = storage.Client(project=project, credentials=credentials).bucket(
        bucket
    )
    return (
        CloudStorageObjectStore(storage_bucket),
        FirestoreFirmwareSnapshotStore(firestore_client),
    )


def _document_data(snapshot: Any) -> dict[str, Any]:
    data = snapshot.to_dict()
    if not isinstance(data, dict):
        raise ValueError("Firestore firmware document has no object data")
    return data


def _require_snapshot_identity(
    value: Mapping[str, Any], snapshot_id: str, manifest_sha256: str
) -> None:
    if (
        value.get("snapshot_id") != snapshot_id
        or value.get("manifest_sha256") != manifest_sha256
    ):
        raise ValueError("Firestore firmware snapshot identity collision")


def _manifest_sha256(manifest: Mapping[str, Any]) -> str:
    body = json.dumps(
        manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
    return hashlib.sha256(body).hexdigest()


def _plain_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(dict(value), ensure_ascii=False, separators=(",", ":")))


def _chunks[ItemT](values: Iterable[ItemT], size: int) -> Iterable[list[ItemT]]:
    chunk: list[ItemT] = []
    for value in values:
        chunk.append(value)
        if len(chunk) == size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk

"""Google Cloud implementations of the normalized mirror persistence boundaries."""

import hashlib
import json
import subprocess
from collections.abc import Iterable, Mapping
from typing import Any

from google.api_core.exceptions import NotFound, PreconditionFailed
from google.auth.credentials import Credentials
from google.cloud import firestore, storage
from google.oauth2.credentials import Credentials as AccessTokenCredentials

from retrostore.mirror.persistence import CatalogSnapshot, ImmutableObject

_SNAPSHOTS_COLLECTION = "catalogSnapshots"
_CONTROL_COLLECTION = "catalogControl"
_ACTIVE_DOCUMENT = "active"
_FIRESTORE_BATCH_SIZE = 450


class CloudStorageObjectStore:
    """Immutable checksum-verifying object storage backed by one private bucket."""

    def __init__(self, bucket: storage.Bucket) -> None:
        self._bucket = bucket

    def put_verified(self, value: ImmutableObject) -> bool:
        actual_sha256 = hashlib.sha256(value.body).hexdigest()
        if actual_sha256 != value.sha256:
            raise ValueError(f"Object body does not match its SHA-256: {value.path}")

        blob = self._bucket.blob(value.path)
        blob.metadata = {"sha256": value.sha256}
        try:
            blob.upload_from_string(
                value.body,
                content_type=value.content_type,
                checksum="auto",
                if_generation_match=0,
            )
            return True
        except PreconditionFailed:
            existing = self.read(value.path)
            if (
                len(existing) != len(value.body)
                or hashlib.sha256(existing).hexdigest() != value.sha256
            ):
                raise ValueError(f"Immutable cloud object collision: {value.path}") from None
            return False

    def read(self, path: str) -> bytes:
        try:
            return bytes(self._bucket.blob(path).download_as_bytes(checksum="auto"))
        except NotFound as error:
            raise ValueError(f"Cloud object is missing: {path}") from error


class FirestoreCatalogSnapshotStore:
    """Stage versioned metadata and atomically switch a validated active pointer."""

    def __init__(self, client: firestore.Client) -> None:
        self._client = client

    def stage(self, snapshot: CatalogSnapshot) -> None:
        root = self._snapshot_reference(snapshot.id)
        existing = root.get()
        if existing.exists:
            existing_data = _document_data(existing)
            _require_snapshot_identity(existing_data, snapshot.id, snapshot.manifest_sha256)
            if existing_data.get("status") == "READY":
                manifest = self._load_snapshot_manifest(
                    snapshot.id, allowed_statuses={"READY"}
                )
                if _manifest_sha256(manifest) != snapshot.manifest_sha256:
                    raise ValueError(
                        "Ready Firestore snapshot does not match its manifest digest"
                    )
                return

        metadata = _plain_mapping(snapshot.metadata)
        root.set({**metadata, "status": "STAGING"})
        for collection_name, documents in snapshot.collections.items():
            collection = root.collection(collection_name)
            for chunk in _chunks(documents.items(), _FIRESTORE_BATCH_SIZE):
                batch = self._client.batch()
                for document_id, document in chunk:
                    batch.set(collection.document(document_id), _plain_mapping(document))
                batch.commit()

        manifest = self._load_snapshot_manifest(snapshot.id, allowed_statuses={"STAGING"})
        if _manifest_sha256(manifest) != snapshot.manifest_sha256:
            raise ValueError("Staged Firestore snapshot does not match its manifest digest")
        root.set({**metadata, "status": "STAGED"})

    def activate(self, snapshot_id: str, manifest_sha256: str) -> None:
        root = self._snapshot_reference(snapshot_id)
        root_snapshot = root.get()
        if not root_snapshot.exists:
            raise ValueError("Catalog snapshot is not staged")
        root_data = _document_data(root_snapshot)
        _require_snapshot_identity(root_data, snapshot_id, manifest_sha256)
        if root_data.get("status") not in {"STAGED", "READY"}:
            raise ValueError("Catalog snapshot is not ready for activation")

        manifest = self._load_snapshot_manifest(
            snapshot_id, allowed_statuses={"STAGED", "READY"}
        )
        if _manifest_sha256(manifest) != manifest_sha256:
            raise ValueError("Catalog snapshot changed before activation")

        batch = self._client.batch()
        batch.set(root, {**root_data, "status": "READY"})
        batch.set(
            self._client.collection(_CONTROL_COLLECTION).document(_ACTIVE_DOCUMENT),
            {
                "snapshot_id": snapshot_id,
                "manifest_sha256": manifest_sha256,
            },
        )
        batch.commit()

    def load_active_manifest(self) -> Mapping[str, Any]:
        active = (
            self._client.collection(_CONTROL_COLLECTION).document(_ACTIVE_DOCUMENT).get()
        )
        if not active.exists:
            raise ValueError("No active Firestore catalog snapshot")
        active_data = _document_data(active)
        snapshot_id = active_data.get("snapshot_id")
        manifest_sha256 = active_data.get("manifest_sha256")
        if not isinstance(snapshot_id, str) or not isinstance(manifest_sha256, str):
            raise ValueError("Active Firestore catalog pointer is malformed")

        manifest = self._load_snapshot_manifest(snapshot_id, allowed_statuses={"READY"})
        if _manifest_sha256(manifest) != manifest_sha256:
            raise ValueError("Active Firestore catalog snapshot failed reconciliation")
        return manifest

    def _load_snapshot_manifest(
        self, snapshot_id: str, *, allowed_statuses: set[str]
    ) -> dict[str, Any]:
        root = self._snapshot_reference(snapshot_id)
        snapshot = root.get()
        if not snapshot.exists:
            raise ValueError("Firestore catalog snapshot metadata is missing")
        metadata = _document_data(snapshot)
        manifest_sha256 = metadata.get("manifest_sha256")
        if not isinstance(manifest_sha256, str):
            raise ValueError("Firestore catalog snapshot digest is missing")
        _require_snapshot_identity(metadata, snapshot_id, manifest_sha256)
        if metadata.get("status") not in allowed_statuses:
            raise ValueError("Firestore catalog snapshot has an invalid status")

        return {
            "schema_version": metadata.get("schema_version"),
            "source": metadata.get("source"),
            "apps": self._collection_documents(root, "apps"),
            "media": self._collection_documents(root, "media"),
            "screenshots": self._collection_documents(root, "screenshots"),
            "reconciliation": metadata.get("reconciliation"),
        }

    def _collection_documents(self, root: Any, collection_name: str) -> list[dict[str, Any]]:
        snapshots = sorted(root.collection(collection_name).stream(), key=lambda item: item.id)
        return [_document_data(snapshot) for snapshot in snapshots]

    def _snapshot_reference(self, snapshot_id: str) -> Any:
        return self._client.collection(_SNAPSHOTS_COLLECTION).document(snapshot_id)


def google_catalog_stores(
    *,
    project: str,
    database: str,
    bucket: str,
    impersonate_service_account: str | None = None,
    credentials: Credentials | None = None,
) -> tuple[CloudStorageObjectStore, FirestoreCatalogSnapshotStore]:
    """Create production adapters for an explicitly named database and bucket."""

    validate_catalog_target(project=project, database=database, bucket=bucket)
    if impersonate_service_account is not None:
        if credentials is not None:
            raise ValueError("Pass credentials or impersonation, not both")
        validate_migration_identity(project, impersonate_service_account)
        credentials = gcloud_impersonated_credentials(
            project=project,
            service_account=impersonate_service_account,
        )

    firestore_client = firestore.Client(
        project=project,
        database=database,
        credentials=credentials,
    )
    storage_bucket = storage.Client(project=project, credentials=credentials).bucket(bucket)
    return (
        CloudStorageObjectStore(storage_bucket),
        FirestoreCatalogSnapshotStore(firestore_client),
    )


def validate_catalog_target(*, project: str, database: str, bucket: str) -> None:
    """Reject implicit or legacy resources before any cloud clients are constructed."""

    if not project or not database or not bucket:
        raise ValueError("Project, database, and bucket must be explicit")
    if database == "(default)":
        raise ValueError("Catalog persistence must not target the legacy default database")
    if bucket in {
        f"{project}.appspot.com",
        f"staging.{project}.appspot.com",
        f"us.artifacts.{project}.appspot.com",
    }:
        raise ValueError("Catalog persistence must not target a legacy bucket")


def migration_service_account(project: str) -> str:
    return f"retrostore-migrator@{project}.iam.gserviceaccount.com"


def validate_migration_identity(project: str, service_account: str) -> None:
    if service_account != migration_service_account(project):
        raise ValueError(
            "Catalog apply must impersonate the dedicated project migration identity"
        )


def gcloud_impersonated_credentials(
    *, project: str, service_account: str
) -> AccessTokenCredentials:
    """Mint a short-lived operator token without creating a service-account key."""

    try:
        completed = subprocess.run(
            [
                "gcloud",
                "auth",
                "print-access-token",
                f"--impersonate-service-account={service_account}",
                f"--project={project}",
                "--quiet",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or "gcloud exited unsuccessfully"
        raise RuntimeError(f"Could not impersonate {service_account}: {detail}") from None
    token = completed.stdout.strip()
    if not token:
        raise RuntimeError("gcloud returned an empty impersonated access token")
    return AccessTokenCredentials(token=token)


def _document_data(snapshot: Any) -> dict[str, Any]:
    data = snapshot.to_dict()
    if not isinstance(data, dict):
        raise ValueError("Firestore catalog document has no object data")
    return data


def _require_snapshot_identity(
    value: Mapping[str, Any], snapshot_id: str, manifest_sha256: str
) -> None:
    if value.get("snapshot_id") != snapshot_id or value.get("manifest_sha256") != manifest_sha256:
        raise ValueError("Firestore catalog snapshot identity collision")


def _manifest_sha256(manifest: Mapping[str, Any]) -> str:
    body = json.dumps(
        manifest,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
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

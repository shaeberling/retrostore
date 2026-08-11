"""Firestore persistence for an isolated normalized catalog working set."""

import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from google.cloud import firestore

from retrostore.migration.admin.working_catalog import WorkingCatalogMaterialization

_CONTROL_COLLECTION = "catalogWorkingControl"
_CONTROL_DOCUMENT = "current"
_AUDIT_COLLECTION = "auditEvents"
_MAX_BATCH_WRITES = 450


class WorkingCatalogConflictError(RuntimeError):
    """The working collection contains data from another source or operation."""


@dataclass(frozen=True, slots=True)
class WorkingCatalogMaterializationReport:
    materialization_id: str
    manifest_sha256: str
    counts: Mapping[str, int]
    documents_created: int
    documents_reused: int
    audit_created: bool


class FirestoreWorkingCatalogStore:
    """Create the initial working set once, without altering active snapshots."""

    def __init__(self, client: firestore.Client) -> None:
        self._client = client

    def materialize(
        self,
        materialization: WorkingCatalogMaterialization,
        *,
        actor: str,
    ) -> WorkingCatalogMaterializationReport:
        if not actor or len(actor) > 320:
            raise ValueError("Working catalog materialization actor is invalid")
        expected_control = _control_identity(materialization)
        control_reference = self._client.collection(_CONTROL_COLLECTION).document(_CONTROL_DOCUMENT)
        current = control_reference.get()
        if current.exists:
            current_data = _document_data(current)
            for field, expected in expected_control.items():
                if current_data.get(field) != expected:
                    raise WorkingCatalogConflictError(
                        "Another catalog working set is already materialized"
                    )
            self._verify_documents(materialization)
            self._verify_audit(materialization, actor=actor)
            total = sum(materialization.counts.values())
            return WorkingCatalogMaterializationReport(
                materialization_id=materialization.id,
                manifest_sha256=materialization.manifest_sha256,
                counts=materialization.counts,
                documents_created=0,
                documents_reused=total,
                audit_created=False,
            )

        missing: list[tuple[Any, dict[str, Any]]] = []
        for collection_name, expected_documents in materialization.collections.items():
            collection = self._client.collection(collection_name)
            existing = {snapshot.id: _document_data(snapshot) for snapshot in collection.stream()}
            for document_id, expected_document in expected_documents.items():
                expected = _plain(expected_document)
                actual = existing.get(document_id)
                if actual is None:
                    missing.append((collection.document(document_id), expected))
                else:
                    raise WorkingCatalogConflictError(
                        f"Working {collection_name} document ID is already in use"
                    )

        required_writes = len(missing) + 2
        if required_writes > _MAX_BATCH_WRITES:
            raise ValueError("Initial working catalog does not fit in one atomic Firestore batch")
        audit_reference = self._client.collection(_AUDIT_COLLECTION).document()
        batch = self._client.batch()
        for reference, document in missing:
            batch.create(reference, document)
        batch.create(
            control_reference,
            {
                **expected_control,
                "source": dict(materialization.source),
                "status": "READY",
                "materializedAt": firestore.SERVER_TIMESTAMP,
            },
        )
        batch.create(
            audit_reference,
            {
                "schemaVersion": 1,
                "eventType": "CATALOG_WORKING_SET_MATERIALIZED",
                "status": "SUCCEEDED",
                "actorUid": actor,
                "targetId": materialization.id,
                "sourceSnapshotId": materialization.source["snapshotId"],
                "manifestSha256": materialization.manifest_sha256,
                "counts": dict(materialization.counts),
                "createdAt": firestore.SERVER_TIMESTAMP,
            },
        )
        batch.commit()
        return WorkingCatalogMaterializationReport(
            materialization_id=materialization.id,
            manifest_sha256=materialization.manifest_sha256,
            counts=materialization.counts,
            documents_created=len(missing),
            documents_reused=0,
            audit_created=True,
        )

    def load_current(self, *, actor: str) -> WorkingCatalogMaterialization:
        """Load and reconcile only the immutable source portion of the working set."""

        if not actor or len(actor) > 320:
            raise ValueError("Working catalog materialization actor is invalid")
        control = self._client.collection(_CONTROL_COLLECTION).document(_CONTROL_DOCUMENT).get()
        if not control.exists:
            raise WorkingCatalogConflictError("No catalog working set is materialized")
        value = _document_data(control)
        if value.get("schemaVersion") != 1 or value.get("status") != "READY":
            raise WorkingCatalogConflictError("Catalog working control is not ready")
        materialization_id = _required_control_string(value, "materializationId")
        manifest_sha256 = _required_control_string(value, "manifestSha256")
        source_snapshot_id = _required_control_string(value, "sourceSnapshotId")
        source_manifest_sha256 = _required_control_string(value, "sourceManifestSha256")
        source_value = value.get("source")
        if not isinstance(source_value, Mapping):
            raise WorkingCatalogConflictError("Catalog working source is malformed")
        source = {
            field: _required_control_string(source_value, field)
            for field in (
                "projectId",
                "exportedAt",
                "highWaterMark",
                "snapshotId",
                "manifestSha256",
            )
        }
        if (
            source["snapshotId"] != source_snapshot_id
            or source["manifestSha256"] != source_manifest_sha256
        ):
            raise WorkingCatalogConflictError(
                "Catalog working source does not match its control record"
            )
        expected_counts = _control_counts(value.get("counts"))
        collections: dict[str, Mapping[str, Mapping[str, Any]]] = {}
        for collection_name in expected_counts:
            documents: dict[str, Mapping[str, Any]] = {}
            for snapshot in self._client.collection(collection_name).stream():
                document = _document_data(snapshot)
                source_kind = document.get("sourceKind")
                if source_kind is None:
                    continue
                if source_kind != "APP_ENGINE_MIRROR":
                    raise WorkingCatalogConflictError(
                        f"Working {collection_name} contains an unknown source kind"
                    )
                if document.get("sourceSnapshotId") != source_snapshot_id:
                    raise WorkingCatalogConflictError(
                        f"Working {collection_name} contains another source snapshot"
                    )
                documents[snapshot.id] = MappingProxyType(_plain(document))
            if len(documents) != expected_counts[collection_name]:
                raise WorkingCatalogConflictError(
                    f"Materialized working {collection_name} count changed"
                )
            collections[collection_name] = MappingProxyType(documents)
        materialization = WorkingCatalogMaterialization(
            id=materialization_id,
            source=MappingProxyType(source),
            collections=MappingProxyType(collections),
            manifest_sha256=manifest_sha256,
        )
        for field, expected in _control_identity(materialization).items():
            if value.get(field) != expected:
                raise WorkingCatalogConflictError("Catalog working control identity changed")
        self._verify_documents(materialization)
        self._verify_audit(materialization, actor=actor)
        return materialization

    def load_staged_changes(
        self,
    ) -> Mapping[str, Mapping[str, Mapping[str, Any]]]:
        """Load isolated new-app documents for candidate construction."""

        app_documents: dict[str, Mapping[str, Any]] = {}
        for snapshot in self._client.collection("apps").stream():
            value = _document_data(snapshot)
            if value.get("sourceKind") is None and value.get("status") == "STAGING":
                app_documents[snapshot.id] = MappingProxyType(deepcopy(value))
        for snapshot in self._client.collection("appDrafts").stream():
            value = _document_data(snapshot)
            if value.get("sourceKind") is None and value.get("status") == "DRAFT":
                if snapshot.id in app_documents:
                    raise WorkingCatalogConflictError(
                        "One app has both a new staging record and a published draft"
                    )
                app_documents[snapshot.id] = MappingProxyType(deepcopy(value))
        author_ids = {
            value.get("authorId")
            for value in app_documents.values()
            if isinstance(value.get("authorId"), str)
        }
        collections: dict[str, Mapping[str, Mapping[str, Any]]] = {
            "apps": MappingProxyType(app_documents)
        }
        author_documents = {}
        for snapshot in self._client.collection("authors").stream():
            value = _document_data(snapshot)
            if snapshot.id in author_ids and value.get("sourceKind") is None:
                author_documents[snapshot.id] = MappingProxyType(deepcopy(value))
        collections["authors"] = MappingProxyType(author_documents)
        for collection_name, draft_collection_name in (
            ("media", "appDraftMedia"),
            ("screenshots", "appDraftScreenshots"),
        ):
            documents = {}
            for snapshot in self._client.collection(collection_name).stream():
                value = _document_data(snapshot)
                if value.get("sourceKind") is None:
                    documents[snapshot.id] = MappingProxyType(deepcopy(value))
            for snapshot in self._client.collection(draft_collection_name).stream():
                value = _document_data(snapshot)
                if value.get("sourceKind") is not None:
                    continue
                if snapshot.id in documents:
                    raise WorkingCatalogConflictError(
                        f"One {collection_name} ID exists in both staging and draft data"
                    )
                documents[snapshot.id] = MappingProxyType(deepcopy(value))
            collections[collection_name] = MappingProxyType(documents)
        return MappingProxyType(collections)

    def _verify_documents(self, materialization: WorkingCatalogMaterialization) -> None:
        for collection_name, expected_documents in materialization.collections.items():
            actual_documents = {
                snapshot.id: _document_data(snapshot)
                for snapshot in self._client.collection(collection_name).stream()
                if snapshot.id in expected_documents
            }
            if set(actual_documents) != set(expected_documents):
                raise WorkingCatalogConflictError(
                    f"Materialized working {collection_name} documents are incomplete"
                )
            for document_id, expected in expected_documents.items():
                if actual_documents[document_id] != _plain(expected):
                    raise WorkingCatalogConflictError(
                        f"Materialized working {collection_name} document changed"
                    )

    def _verify_audit(
        self,
        materialization: WorkingCatalogMaterialization,
        *,
        actor: str,
    ) -> None:
        matches = []
        for snapshot in self._client.collection(_AUDIT_COLLECTION).stream():
            value = _document_data(snapshot)
            if (
                value.get("eventType") == "CATALOG_WORKING_SET_MATERIALIZED"
                and value.get("targetId") == materialization.id
            ):
                matches.append(value)
        if len(matches) != 1:
            raise WorkingCatalogConflictError(
                "Working catalog materialization audit event is missing or duplicated"
            )
        audit = matches[0]
        expected = {
            "schemaVersion": 1,
            "eventType": "CATALOG_WORKING_SET_MATERIALIZED",
            "status": "SUCCEEDED",
            "actorUid": actor,
            "targetId": materialization.id,
            "sourceSnapshotId": materialization.source["snapshotId"],
            "manifestSha256": materialization.manifest_sha256,
            "counts": dict(materialization.counts),
        }
        if any(audit.get(field) != value for field, value in expected.items()):
            raise WorkingCatalogConflictError("Working catalog materialization audit event changed")


def _control_identity(
    materialization: WorkingCatalogMaterialization,
) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "materializationId": materialization.id,
        "manifestSha256": materialization.manifest_sha256,
        "sourceSnapshotId": materialization.source["snapshotId"],
        "sourceManifestSha256": materialization.source["manifestSha256"],
        "counts": dict(materialization.counts),
    }


def _document_data(snapshot: Any) -> dict[str, Any]:
    value = snapshot.to_dict()
    if not isinstance(value, dict):
        raise ValueError("Working catalog document is malformed")
    return value


def _plain(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(dict(value), ensure_ascii=False, separators=(",", ":")))


def _required_control_string(value: Mapping[str, Any], field: str) -> str:
    result = value.get(field)
    if not isinstance(result, str) or not result:
        raise WorkingCatalogConflictError(f"Catalog working control field {field} is malformed")
    return result


def _control_counts(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping) or set(value) != {
        "apps",
        "authors",
        "media",
        "screenshots",
    }:
        raise WorkingCatalogConflictError("Catalog working counts are malformed")
    result = dict(value)
    if any(
        isinstance(count, bool) or not isinstance(count, int) or count < 0
        for count in result.values()
    ):
        raise WorkingCatalogConflictError("Catalog working counts are malformed")
    return result  # type: ignore[return-value]

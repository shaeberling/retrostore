"""Firestore persistence for an isolated normalized catalog working set."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from google.cloud import firestore

from retrostore.admin.working_catalog import WorkingCatalogMaterialization

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
        control_reference = self._client.collection(_CONTROL_COLLECTION).document(
            _CONTROL_DOCUMENT
        )
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
            existing = {
                snapshot.id: _document_data(snapshot) for snapshot in collection.stream()
            }
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
            raise ValueError(
                "Initial working catalog does not fit in one atomic Firestore batch"
            )
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

    def _verify_documents(
        self, materialization: WorkingCatalogMaterialization
    ) -> None:
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
            raise WorkingCatalogConflictError(
                "Working catalog materialization audit event changed"
            )


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

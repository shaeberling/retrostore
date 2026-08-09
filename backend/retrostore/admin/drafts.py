"""Copy-on-write metadata drafts for materialized published applications."""

import hashlib
import unicodedata
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Protocol

from google.cloud import firestore

from retrostore.admin.auth import AdminIdentity
from retrostore.admin.staging import (
    StagedApp,
    StagedAppDraft,
    StagingAuthorizationError,
    StagingConflictError,
    StagingNotFoundError,
    _staged_app,
)

_APPS_COLLECTION = "apps"
_DRAFTS_COLLECTION = "appDrafts"
_AUDIT_COLLECTION = "auditEvents"


class AdminPublishedAppDrafts(Protocol):
    def create(self, *, identity: AdminIdentity, app_id: str) -> StagedApp: ...

    def get(self, identity: AdminIdentity, app_id: str) -> StagedApp | None: ...

    def update(
        self,
        *,
        identity: AdminIdentity,
        app_id: str,
        expected_revision: int,
        draft: StagedAppDraft,
    ) -> StagedApp: ...

    def discard(
        self,
        *,
        identity: AdminIdentity,
        app_id: str,
        expected_revision: int,
    ) -> None: ...


class FirestorePublishedAppDrafts:
    """Store editable overlays separately from immutable source documents."""

    def __init__(self, client: firestore.Client) -> None:
        self._client = client

    def create(self, *, identity: AdminIdentity, app_id: str) -> StagedApp:
        if not identity.is_administrator:
            raise StagingAuthorizationError(
                "Only administrators can draft a published baseline record"
            )
        app_id = _document_id(app_id)
        source_reference = self._client.collection(_APPS_COLLECTION).document(app_id)
        draft_reference = self._client.collection(_DRAFTS_COLLECTION).document(app_id)
        audit_reference = self._client.collection(_AUDIT_COLLECTION).document()
        transaction = self._client.transaction()

        @firestore.transactional
        def create_draft(transaction: Any) -> StagedApp:
            source_snapshot = source_reference.get(transaction=transaction)
            if not source_snapshot.exists:
                raise StagingNotFoundError("Published app does not exist")
            source_document = _document_data(source_snapshot)
            source = _staged_app(source_snapshot.id, source_document)
            if source.status != "PUBLISHED":
                raise StagingConflictError("App is not a published baseline record")
            source_snapshot_id = _required_string(
                source_document, "sourceSnapshotId", "Published app source snapshot"
            )
            source_fingerprint = _required_string(
                source_document, "sourceFingerprint", "Published app fingerprint"
            )
            existing_snapshot = draft_reference.get(transaction=transaction)
            if existing_snapshot.exists:
                existing_document = _document_data(existing_snapshot)
                existing = _staged_app(existing_snapshot.id, existing_document)
                _require_owner(identity, existing)
                if (
                    existing.status != "DRAFT"
                    or existing_document.get("baseSnapshotId") != source_snapshot_id
                    or existing_document.get("baseSourceFingerprint")
                    != source_fingerprint
                ):
                    raise StagingConflictError(
                        "Existing draft is based on another published revision"
                    )
                return existing

            value = replace(
                source,
                publisher_uid=identity.uid,
                revision=1,
                status="DRAFT",
            )
            transaction.create(
                draft_reference,
                {
                    "schemaVersion": 1,
                    "name": value.name,
                    "version": value.version,
                    "description": value.description,
                    "platform": "TRS80",
                    "model": value.model,
                    "categories": [value.category],
                    "releaseYear": value.release_year,
                    "authorId": value.author_id,
                    "authorName": value.author_name,
                    "sourceAuthorId": source_document.get("sourceAuthorId"),
                    "baseAuthorId": value.author_id,
                    "baseAuthorName": value.author_name,
                    "baseSourceAuthorId": source_document.get("sourceAuthorId"),
                    "publisherUid": identity.uid,
                    "publisherEmail": value.publisher_email,
                    "draftOwnerEmail": identity.email,
                    "mediaSlots": {
                        "disks": list(value.disk_media_ids),
                        "cassette": value.cassette_media_id,
                        "command": value.command_media_id,
                        "basic": value.basic_media_id,
                    },
                    "screenshotIds": list(value.screenshot_ids),
                    "status": "DRAFT",
                    "revision": 1,
                    "baseSnapshotId": source_snapshot_id,
                    "baseSourceFingerprint": source_fingerprint,
                    "firstPublishedAtMs": source_document.get("firstPublishedAtMs"),
                    "baseUpdatedAtMs": source_document.get("updatedAtMs"),
                    "createdAt": firestore.SERVER_TIMESTAMP,
                    "updatedAt": firestore.SERVER_TIMESTAMP,
                },
            )
            transaction.create(
                audit_reference,
                {
                    "schemaVersion": 1,
                    "eventType": "PUBLISHED_APP_DRAFT_CREATED",
                    "status": "SUCCEEDED",
                    "actorUid": identity.uid,
                    "targetId": app_id,
                    "baseSnapshotId": source_snapshot_id,
                    "createdAt": firestore.SERVER_TIMESTAMP,
                },
            )
            return value

        return create_draft(transaction)

    def get(self, identity: AdminIdentity, app_id: str) -> StagedApp | None:
        try:
            app_id = _document_id(app_id)
        except StagingNotFoundError:
            return None
        snapshot = self._client.collection(_DRAFTS_COLLECTION).document(app_id).get()
        if not snapshot.exists:
            return None
        value = _staged_app(snapshot.id, _document_data(snapshot))
        if value.status != "DRAFT":
            raise ValueError("Published app draft has an invalid status")
        _require_owner(identity, value)
        return value

    def update(
        self,
        *,
        identity: AdminIdentity,
        app_id: str,
        expected_revision: int,
        draft: StagedAppDraft,
    ) -> StagedApp:
        app_id = _document_id(app_id)
        _require_revision(expected_revision)
        reference = self._client.collection(_DRAFTS_COLLECTION).document(app_id)
        audit_reference = self._client.collection(_AUDIT_COLLECTION).document()
        transaction = self._client.transaction()

        @firestore.transactional
        def update_draft(transaction: Any) -> StagedApp:
            snapshot = reference.get(transaction=transaction)
            if not snapshot.exists:
                raise StagingNotFoundError("Published app draft does not exist")
            document = _document_data(snapshot)
            current = _staged_app(snapshot.id, document)
            if current.status != "DRAFT":
                raise StagingConflictError("Published app draft is not editable")
            _require_owner(identity, current)
            if current.revision != expected_revision:
                raise StagingConflictError(
                    "The draft changed concurrently; reload before trying again"
                )
            author_name = _normalized_author_name(draft.author_name)
            base_author_id = _required_string(
                document, "baseAuthorId", "Published app base author ID"
            )
            base_author_name = _required_string(
                document, "baseAuthorName", "Published app base author name"
            )
            if author_name == base_author_name:
                author_id = base_author_id
                source_author_id = document.get("baseSourceAuthorId")
            else:
                author_id = _draft_author_id(author_name)
                source_author_id = None
            updated = replace(
                current,
                name=draft.name,
                version=draft.version,
                description=draft.description,
                release_year=draft.release_year,
                model=draft.model,
                category=draft.category,
                author_id=author_id,
                author_name=author_name,
                revision=current.revision + 1,
            )
            transaction.set(
                reference,
                {
                    "name": updated.name,
                    "version": updated.version,
                    "description": updated.description,
                    "model": updated.model,
                    "categories": [updated.category],
                    "releaseYear": updated.release_year,
                    "authorId": updated.author_id,
                    "authorName": updated.author_name,
                    "sourceAuthorId": source_author_id,
                    "revision": updated.revision,
                    "updatedAt": firestore.SERVER_TIMESTAMP,
                },
                merge=True,
            )
            transaction.create(
                audit_reference,
                {
                    "schemaVersion": 1,
                    "eventType": "PUBLISHED_APP_DRAFT_UPDATED",
                    "status": "SUCCEEDED",
                    "actorUid": identity.uid,
                    "targetId": app_id,
                    "previousRevision": current.revision,
                    "revision": updated.revision,
                    "createdAt": firestore.SERVER_TIMESTAMP,
                },
            )
            return updated

        return update_draft(transaction)

    def discard(
        self,
        *,
        identity: AdminIdentity,
        app_id: str,
        expected_revision: int,
    ) -> None:
        app_id = _document_id(app_id)
        _require_revision(expected_revision)
        reference = self._client.collection(_DRAFTS_COLLECTION).document(app_id)
        audit_reference = self._client.collection(_AUDIT_COLLECTION).document()
        transaction = self._client.transaction()

        @firestore.transactional
        def discard_draft(transaction: Any) -> None:
            snapshot = reference.get(transaction=transaction)
            if not snapshot.exists:
                raise StagingNotFoundError("Published app draft does not exist")
            current = _staged_app(snapshot.id, _document_data(snapshot))
            if current.status != "DRAFT":
                raise StagingConflictError("Published app draft is not discardable")
            _require_owner(identity, current)
            if current.revision != expected_revision:
                raise StagingConflictError(
                    "The draft changed concurrently; reload before trying again"
                )
            transaction.delete(reference)
            transaction.create(
                audit_reference,
                {
                    "schemaVersion": 1,
                    "eventType": "PUBLISHED_APP_DRAFT_DISCARDED",
                    "status": "SUCCEEDED",
                    "actorUid": identity.uid,
                    "targetId": app_id,
                    "discardedRevision": current.revision,
                    "createdAt": firestore.SERVER_TIMESTAMP,
                },
            )

        discard_draft(transaction)


def _document_data(snapshot: Any) -> dict[str, Any]:
    value = snapshot.to_dict()
    if not isinstance(value, dict):
        raise ValueError("Published app draft document is malformed")
    return value


def _document_id(value: str) -> str:
    if (
        not value
        or value in {".", ".."}
        or "/" in value
        or len(value.encode()) > 1_500
        or (value.startswith("__") and value.endswith("__"))
    ):
        raise StagingNotFoundError("Published app does not exist")
    return value


def _required_string(value: Mapping[str, Any], field: str, label: str) -> str:
    result = value.get(field)
    if not isinstance(result, str) or not result:
        raise ValueError(f"{label} is invalid")
    return result


def _require_owner(identity: AdminIdentity, draft: StagedApp) -> None:
    if not identity.is_administrator and draft.publisher_uid != identity.uid:
        raise StagingAuthorizationError("Publisher does not own this draft")


def _require_revision(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise StagingConflictError("Published app draft revision is invalid")


def _normalized_author_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _draft_author_id(name: str) -> str:
    return f"draft-{hashlib.sha256(name.casefold().encode()).hexdigest()[:32]}"

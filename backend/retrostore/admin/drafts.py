"""Copy-on-write metadata drafts for materialized published applications."""

import hashlib
import unicodedata
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Protocol

from google.cloud import firestore

from retrostore.admin.assets import (
    StagingObjectStore,
    ValidatedAssetUpload,
    validate_media_slot,
)
from retrostore.admin.auth import AdminIdentity
from retrostore.admin.staging import (
    StagedApp,
    StagedAppDetail,
    StagedAppDraft,
    StagedMedia,
    StagedScreenshot,
    StagingAuthorizationError,
    StagingConflictError,
    StagingNotFoundError,
    _media_slots_document,
    _staged_app,
    _staged_media,
    _staged_screenshot,
    _with_media_slot,
    new_staged_asset_id,
)

_APPS_COLLECTION = "apps"
_DRAFTS_COLLECTION = "appDrafts"
_DRAFT_MEDIA_COLLECTION = "appDraftMedia"
_DRAFT_SCREENSHOTS_COLLECTION = "appDraftScreenshots"
_SOURCE_MEDIA_COLLECTION = "media"
_SOURCE_SCREENSHOTS_COLLECTION = "screenshots"
_AUDIT_COLLECTION = "auditEvents"


class AdminPublishedAppDrafts(Protocol):
    def create(self, *, identity: AdminIdentity, app_id: str) -> StagedApp: ...

    def get(self, identity: AdminIdentity, app_id: str) -> StagedApp | None: ...

    def get_detail(
        self, identity: AdminIdentity, app_id: str
    ) -> StagedAppDetail | None: ...

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

    def upload_media(
        self,
        *,
        identity: AdminIdentity,
        app_id: str,
        expected_revision: int,
        slot: str,
        upload: ValidatedAssetUpload,
    ) -> StagedApp: ...

    def delete_media(
        self,
        *,
        identity: AdminIdentity,
        app_id: str,
        media_id: str,
        expected_revision: int,
    ) -> StagedApp: ...

    def upload_screenshot(
        self,
        *,
        identity: AdminIdentity,
        app_id: str,
        expected_revision: int,
        upload: ValidatedAssetUpload,
    ) -> StagedApp: ...

    def move_screenshot(
        self,
        *,
        identity: AdminIdentity,
        app_id: str,
        screenshot_id: str,
        expected_revision: int,
        direction: str,
    ) -> StagedApp: ...

    def delete_screenshot(
        self,
        *,
        identity: AdminIdentity,
        app_id: str,
        screenshot_id: str,
        expected_revision: int,
    ) -> StagedApp: ...

    def read_screenshot(
        self, identity: AdminIdentity, app_id: str, screenshot_id: str
    ) -> tuple[StagedScreenshot, bytes] | None: ...


class FirestorePublishedAppDrafts:
    """Store editable overlays separately from immutable source documents."""

    def __init__(
        self, client: firestore.Client, object_store: StagingObjectStore | None = None
    ) -> None:
        self._client = client
        self._object_store = object_store

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

    def get_detail(
        self, identity: AdminIdentity, app_id: str
    ) -> StagedAppDetail | None:
        app = self.get(identity, app_id)
        if app is None:
            return None
        media = tuple(
            self._load_media(media_id, app.id)
            for media_id in _ordered_media_ids(app)
        )
        screenshots = tuple(
            self._load_screenshot(screenshot_id, app.id)
            for screenshot_id in app.screenshot_ids
        )
        return StagedAppDetail(app=app, media=media, screenshots=screenshots)

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
        asset_snapshots = {
            collection_name: tuple(
                snapshot
                for snapshot in self._client.collection(collection_name).stream()
                if _document_data(snapshot).get("appId") == app_id
            )
            for collection_name in (
                _DRAFT_MEDIA_COLLECTION,
                _DRAFT_SCREENSHOTS_COLLECTION,
            )
        }
        if any(asset_snapshots.values()):
            self._object_store_or_error()
        audit_reference = self._client.collection(_AUDIT_COLLECTION).document()
        transaction = self._client.transaction()
        object_paths: list[str] = []

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
            checked_assets = []
            for collection_name, snapshots in asset_snapshots.items():
                for asset_snapshot in snapshots:
                    asset_reference = self._client.collection(
                        collection_name
                    ).document(asset_snapshot.id)
                    checked = asset_reference.get(transaction=transaction)
                    if not checked.exists:
                        raise StagingConflictError(
                            "A draft asset changed concurrently; reload before trying again"
                        )
                    document = _document_data(checked)
                    if document.get("appId") != app_id:
                        raise ValueError("Published app draft asset ownership changed")
                    object_path = document.get("objectPath")
                    if not isinstance(object_path, str) or not object_path:
                        raise ValueError("Published app draft asset path is invalid")
                    object_paths.append(object_path)
                    checked_assets.append(asset_reference)
            for asset_reference in checked_assets:
                transaction.delete(asset_reference)
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
        if object_paths:
            object_store = self._object_store_or_error()
            for object_path in object_paths:
                object_store.delete(object_path)

    def upload_media(
        self,
        *,
        identity: AdminIdentity,
        app_id: str,
        expected_revision: int,
        slot: str,
        upload: ValidatedAssetUpload,
    ) -> StagedApp:
        app_id = _document_id(app_id)
        _require_revision(expected_revision)
        media_type, _ = validate_media_slot(slot)
        object_store = self._object_store_or_error()
        media_id = new_staged_asset_id()
        object_path = f"media/{app_id}/{media_id}/{upload.sha256}"
        if not object_store.put_verified(
            path=object_path,
            body=upload.body,
            sha256=upload.sha256,
            content_type=upload.content_type,
        ):
            raise StagingConflictError("Generated draft media identifier collided")

        app_reference = self._client.collection(_DRAFTS_COLLECTION).document(app_id)
        media_reference = self._client.collection(_DRAFT_MEDIA_COLLECTION).document(
            media_id
        )
        audit_reference = self._client.collection(_AUDIT_COLLECTION).document()
        transaction = self._client.transaction()
        replaced_object_path: str | None = None

        @firestore.transactional
        def commit_media(transaction: Any) -> StagedApp:
            nonlocal replaced_object_path
            current = _transaction_draft(
                transaction, app_reference, identity, expected_revision
            )
            replaced_id = _media_id_for_slot(current, slot)
            if replaced_id is not None:
                replaced_reference = self._client.collection(
                    _DRAFT_MEDIA_COLLECTION
                ).document(replaced_id)
                replaced_snapshot = replaced_reference.get(transaction=transaction)
                if replaced_snapshot.exists:
                    replaced = _staged_media(
                        replaced_snapshot.id, _document_data(replaced_snapshot)
                    )
                    if replaced.app_id != app_id or replaced.slot != slot:
                        raise ValueError("Draft media reference is inconsistent")
                    replaced_object_path = replaced.object_path
                    transaction.delete(replaced_reference)
            updated = replace(
                _with_media_slot(current, slot, media_id),
                revision=current.revision + 1,
            )
            transaction.create(
                media_reference,
                {
                    "schemaVersion": 1,
                    "appId": app_id,
                    "mediaType": media_type,
                    "slot": slot,
                    "filename": upload.filename,
                    "description": upload.description,
                    "contentType": upload.content_type,
                    "objectPath": object_path,
                    "size": upload.size,
                    "sha256": upload.sha256,
                    "publisherUid": current.publisher_uid,
                    "createdAt": firestore.SERVER_TIMESTAMP,
                },
            )
            transaction.set(
                app_reference,
                {
                    "mediaSlots": _media_slots_document(updated),
                    "revision": updated.revision,
                    "updatedAt": firestore.SERVER_TIMESTAMP,
                },
                merge=True,
            )
            transaction.create(
                audit_reference,
                _asset_audit(
                    "PUBLISHED_APP_DRAFT_MEDIA_UPLOADED",
                    identity,
                    media_id,
                    app_id,
                    current,
                    updated,
                    slot=slot,
                    replacedAssetId=replaced_id,
                ),
            )
            return updated

        try:
            updated = commit_media(transaction)
        except Exception:
            object_store.delete(object_path)
            raise
        if replaced_object_path is not None:
            object_store.delete(replaced_object_path)
        return updated

    def delete_media(
        self,
        *,
        identity: AdminIdentity,
        app_id: str,
        media_id: str,
        expected_revision: int,
    ) -> StagedApp:
        app_id = _document_id(app_id)
        media_id = _document_id(media_id)
        _require_revision(expected_revision)
        app_reference = self._client.collection(_DRAFTS_COLLECTION).document(app_id)
        media_reference = self._client.collection(_DRAFT_MEDIA_COLLECTION).document(
            media_id
        )
        audit_reference = self._client.collection(_AUDIT_COLLECTION).document()
        transaction = self._client.transaction()
        object_path: str | None = None

        @firestore.transactional
        def commit_delete(transaction: Any) -> StagedApp:
            nonlocal object_path
            current = _transaction_draft(
                transaction, app_reference, identity, expected_revision
            )
            slot = _slot_for_media_id(current, media_id)
            if slot is None:
                raise StagingNotFoundError("Draft media is not attached to this app")
            snapshot = media_reference.get(transaction=transaction)
            inherited = not snapshot.exists
            if snapshot.exists:
                media = _staged_media(snapshot.id, _document_data(snapshot))
                if media.app_id != app_id or media.slot != slot:
                    raise ValueError("Draft media reference is inconsistent")
                object_path = media.object_path
                transaction.delete(media_reference)
            updated = replace(
                _with_media_slot(current, slot, None),
                revision=current.revision + 1,
            )
            transaction.set(
                app_reference,
                {
                    "mediaSlots": _media_slots_document(updated),
                    "revision": updated.revision,
                    "updatedAt": firestore.SERVER_TIMESTAMP,
                },
                merge=True,
            )
            transaction.create(
                audit_reference,
                _asset_audit(
                    "PUBLISHED_APP_DRAFT_MEDIA_REMOVED",
                    identity,
                    media_id,
                    app_id,
                    current,
                    updated,
                    slot=slot,
                    inherited=inherited,
                ),
            )
            return updated

        updated = commit_delete(transaction)
        if object_path is not None:
            self._object_store_or_error().delete(object_path)
        return updated

    def upload_screenshot(
        self,
        *,
        identity: AdminIdentity,
        app_id: str,
        expected_revision: int,
        upload: ValidatedAssetUpload,
    ) -> StagedApp:
        app_id = _document_id(app_id)
        _require_revision(expected_revision)
        if upload.extension is None or not upload.content_type.startswith("image/"):
            raise ValueError("Validated screenshot format is missing")
        object_store = self._object_store_or_error()
        screenshot_id = new_staged_asset_id()
        object_path = (
            f"screenshots/{app_id}/{screenshot_id}/{upload.sha256}.{upload.extension}"
        )
        if not object_store.put_verified(
            path=object_path,
            body=upload.body,
            sha256=upload.sha256,
            content_type=upload.content_type,
        ):
            raise StagingConflictError("Generated draft screenshot identifier collided")

        app_reference = self._client.collection(_DRAFTS_COLLECTION).document(app_id)
        screenshot_reference = self._client.collection(
            _DRAFT_SCREENSHOTS_COLLECTION
        ).document(screenshot_id)
        audit_reference = self._client.collection(_AUDIT_COLLECTION).document()
        transaction = self._client.transaction()

        @firestore.transactional
        def commit_screenshot(transaction: Any) -> StagedApp:
            current = _transaction_draft(
                transaction, app_reference, identity, expected_revision
            )
            updated = replace(
                current,
                screenshot_ids=(*current.screenshot_ids, screenshot_id),
                revision=current.revision + 1,
            )
            transaction.create(
                screenshot_reference,
                {
                    "schemaVersion": 1,
                    "appId": app_id,
                    "filename": upload.filename,
                    "contentType": upload.content_type,
                    "objectPath": object_path,
                    "size": upload.size,
                    "sha256": upload.sha256,
                    "publisherUid": current.publisher_uid,
                    "position": len(current.screenshot_ids),
                    "createdAt": firestore.SERVER_TIMESTAMP,
                },
            )
            transaction.set(
                app_reference,
                {
                    "screenshotIds": list(updated.screenshot_ids),
                    "revision": updated.revision,
                    "updatedAt": firestore.SERVER_TIMESTAMP,
                },
                merge=True,
            )
            transaction.create(
                audit_reference,
                _asset_audit(
                    "PUBLISHED_APP_DRAFT_SCREENSHOT_UPLOADED",
                    identity,
                    screenshot_id,
                    app_id,
                    current,
                    updated,
                    position=len(current.screenshot_ids),
                ),
            )
            return updated

        try:
            return commit_screenshot(transaction)
        except Exception:
            object_store.delete(object_path)
            raise

    def move_screenshot(
        self,
        *,
        identity: AdminIdentity,
        app_id: str,
        screenshot_id: str,
        expected_revision: int,
        direction: str,
    ) -> StagedApp:
        app_id = _document_id(app_id)
        screenshot_id = _document_id(screenshot_id)
        _require_revision(expected_revision)
        if direction not in {"up", "down"}:
            raise ValueError("Screenshot direction must be up or down")
        app_reference = self._client.collection(_DRAFTS_COLLECTION).document(app_id)
        audit_reference = self._client.collection(_AUDIT_COLLECTION).document()
        transaction = self._client.transaction()

        @firestore.transactional
        def commit_move(transaction: Any) -> StagedApp:
            current = _transaction_draft(
                transaction, app_reference, identity, expected_revision
            )
            if screenshot_id not in current.screenshot_ids:
                raise StagingNotFoundError(
                    "Draft screenshot is not attached to this app"
                )
            ids = list(current.screenshot_ids)
            old_position = ids.index(screenshot_id)
            new_position = old_position + (-1 if direction == "up" else 1)
            if not 0 <= new_position < len(ids):
                raise StagingConflictError("Screenshot is already at that boundary")
            ids[old_position], ids[new_position] = ids[new_position], ids[old_position]
            draft_positions = []
            for position in (old_position, new_position):
                reference = self._client.collection(
                    _DRAFT_SCREENSHOTS_COLLECTION
                ).document(ids[position])
                snapshot = reference.get(transaction=transaction)
                if snapshot.exists:
                    value = _staged_screenshot(
                        snapshot.id, _document_data(snapshot)
                    )
                    if value.app_id != app_id:
                        raise ValueError("Draft screenshot reference is inconsistent")
                    draft_positions.append((reference, position))
            for reference, position in draft_positions:
                transaction.set(reference, {"position": position}, merge=True)
            updated = replace(
                current,
                screenshot_ids=tuple(ids),
                revision=current.revision + 1,
            )
            transaction.set(
                app_reference,
                {
                    "screenshotIds": ids,
                    "revision": updated.revision,
                    "updatedAt": firestore.SERVER_TIMESTAMP,
                },
                merge=True,
            )
            transaction.create(
                audit_reference,
                _asset_audit(
                    "PUBLISHED_APP_DRAFT_SCREENSHOT_MOVED",
                    identity,
                    screenshot_id,
                    app_id,
                    current,
                    updated,
                    previousPosition=old_position,
                    position=new_position,
                ),
            )
            return updated

        return commit_move(transaction)

    def delete_screenshot(
        self,
        *,
        identity: AdminIdentity,
        app_id: str,
        screenshot_id: str,
        expected_revision: int,
    ) -> StagedApp:
        app_id = _document_id(app_id)
        screenshot_id = _document_id(screenshot_id)
        _require_revision(expected_revision)
        app_reference = self._client.collection(_DRAFTS_COLLECTION).document(app_id)
        screenshot_reference = self._client.collection(
            _DRAFT_SCREENSHOTS_COLLECTION
        ).document(screenshot_id)
        audit_reference = self._client.collection(_AUDIT_COLLECTION).document()
        transaction = self._client.transaction()
        object_path: str | None = None

        @firestore.transactional
        def commit_delete(transaction: Any) -> StagedApp:
            nonlocal object_path
            current = _transaction_draft(
                transaction, app_reference, identity, expected_revision
            )
            if screenshot_id not in current.screenshot_ids:
                raise StagingNotFoundError(
                    "Draft screenshot is not attached to this app"
                )
            position = current.screenshot_ids.index(screenshot_id)
            snapshot = screenshot_reference.get(transaction=transaction)
            inherited = not snapshot.exists
            if snapshot.exists:
                screenshot = _staged_screenshot(
                    snapshot.id, _document_data(snapshot)
                )
                if screenshot.app_id != app_id:
                    raise ValueError("Draft screenshot reference is inconsistent")
                object_path = screenshot.object_path
            ids = tuple(item for item in current.screenshot_ids if item != screenshot_id)
            position_updates = []
            for new_position, remaining_id in enumerate(ids[position:], start=position):
                reference = self._client.collection(
                    _DRAFT_SCREENSHOTS_COLLECTION
                ).document(remaining_id)
                remaining = reference.get(transaction=transaction)
                if remaining.exists:
                    position_updates.append((reference, new_position))
            if snapshot.exists:
                transaction.delete(screenshot_reference)
            for reference, new_position in position_updates:
                transaction.set(reference, {"position": new_position}, merge=True)
            updated = replace(
                current,
                screenshot_ids=ids,
                revision=current.revision + 1,
            )
            transaction.set(
                app_reference,
                {
                    "screenshotIds": list(ids),
                    "revision": updated.revision,
                    "updatedAt": firestore.SERVER_TIMESTAMP,
                },
                merge=True,
            )
            transaction.create(
                audit_reference,
                _asset_audit(
                    "PUBLISHED_APP_DRAFT_SCREENSHOT_REMOVED",
                    identity,
                    screenshot_id,
                    app_id,
                    current,
                    updated,
                    previousPosition=position,
                    inherited=inherited,
                ),
            )
            return updated

        updated = commit_delete(transaction)
        if object_path is not None:
            self._object_store_or_error().delete(object_path)
        return updated

    def read_screenshot(
        self, identity: AdminIdentity, app_id: str, screenshot_id: str
    ) -> tuple[StagedScreenshot, bytes] | None:
        app = self.get(identity, app_id)
        if app is None or screenshot_id not in app.screenshot_ids:
            return None
        screenshot = self._load_screenshot(_document_id(screenshot_id), app.id)
        body = self._object_store_or_error().read(screenshot.object_path)
        if (
            len(body) != screenshot.size
            or hashlib.sha256(body).hexdigest() != screenshot.sha256
        ):
            raise ValueError("Published app draft screenshot failed verification")
        return screenshot, body

    def _load_media(self, media_id: str, app_id: str) -> StagedMedia:
        snapshot = self._draft_or_source_snapshot(
            _DRAFT_MEDIA_COLLECTION, _SOURCE_MEDIA_COLLECTION, media_id
        )
        media = _staged_media(snapshot.id, _document_data(snapshot))
        if media.app_id != app_id:
            raise ValueError("Published app draft media belongs to another app")
        return media

    def _load_screenshot(self, screenshot_id: str, app_id: str) -> StagedScreenshot:
        snapshot = self._draft_or_source_snapshot(
            _DRAFT_SCREENSHOTS_COLLECTION,
            _SOURCE_SCREENSHOTS_COLLECTION,
            screenshot_id,
        )
        screenshot = _staged_screenshot(snapshot.id, _document_data(snapshot))
        if screenshot.app_id != app_id:
            raise ValueError("Published app draft screenshot belongs to another app")
        return screenshot

    def _draft_or_source_snapshot(
        self, draft_collection: str, source_collection: str, document_id: str
    ) -> Any:
        snapshot = self._client.collection(draft_collection).document(document_id).get()
        if not snapshot.exists:
            snapshot = self._client.collection(source_collection).document(document_id).get()
        if not snapshot.exists:
            raise ValueError("Published app draft references a missing asset")
        return snapshot

    def _object_store_or_error(self) -> StagingObjectStore:
        if self._object_store is None:
            raise ValueError("Published app draft object storage is not configured")
        return self._object_store


def _transaction_draft(
    transaction: Any,
    reference: Any,
    identity: AdminIdentity,
    expected_revision: int,
) -> StagedApp:
    snapshot = reference.get(transaction=transaction)
    if not snapshot.exists:
        raise StagingNotFoundError("Published app draft does not exist")
    current = _staged_app(snapshot.id, _document_data(snapshot))
    if current.status != "DRAFT":
        raise StagingConflictError("Published app draft is not editable")
    _require_owner(identity, current)
    if current.revision != expected_revision:
        raise StagingConflictError(
            "The draft changed concurrently; reload before trying again"
        )
    return current


def _ordered_media_ids(app: StagedApp) -> tuple[str, ...]:
    values = (
        *app.disk_media_ids,
        app.cassette_media_id,
        app.command_media_id,
        app.basic_media_id,
    )
    result = tuple(value for value in values if value is not None)
    if len(result) != len(set(result)):
        raise ValueError("Published app draft media IDs are not unique")
    return result


def _media_id_for_slot(app: StagedApp, slot: str) -> str | None:
    _, position = validate_media_slot(slot)
    if position is not None:
        return app.disk_media_ids[position]
    return {
        "cassette": app.cassette_media_id,
        "command": app.command_media_id,
        "basic": app.basic_media_id,
    }[slot]


def _slot_for_media_id(app: StagedApp, media_id: str) -> str | None:
    for slot in (
        "disk-1",
        "disk-2",
        "disk-3",
        "disk-4",
        "cassette",
        "command",
        "basic",
    ):
        if _media_id_for_slot(app, slot) == media_id:
            return slot
    return None


def _asset_audit(
    event_type: str,
    identity: AdminIdentity,
    target_id: str,
    app_id: str,
    current: StagedApp,
    updated: StagedApp,
    **extra: object,
) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "eventType": event_type,
        "status": "SUCCEEDED",
        "actorUid": identity.uid,
        "targetId": target_id,
        "appId": app_id,
        "previousRevision": current.revision,
        "revision": updated.revision,
        "createdAt": firestore.SERVER_TIMESTAMP,
        **extra,
    }


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

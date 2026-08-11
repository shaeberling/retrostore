"""Application management and persistence for the administration service."""

import hashlib
import json
import time
import unicodedata
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Protocol

from google.cloud import firestore

from retrostore.admin.assets import (
    AssetStore,
    ValidatedAssetUpload,
    validate_media_slot,
)
from retrostore.admin.auth import AdminIdentity
from retrostore.admin.rpk import ValidatedRpk

APP_MODELS = ("MODEL_I", "MODEL_III", "MODEL_4", "MODEL_4P")
APP_CATEGORIES = ("GAME", "GAME_ARCADE", "OFFICE", "OS", "OTHER")
_APPS_COLLECTION = "apps"
_AUTHORS_COLLECTION = "authors"
_AUDIT_COLLECTION = "auditEvents"
_MEDIA_COLLECTION = "media"
_SCREENSHOTS_COLLECTION = "screenshots"


class AppAuthorizationError(PermissionError):
    """The current publisher does not own the requested application."""


class AppConflictError(RuntimeError):
    """An application write conflicts with a concurrent or reused identifier."""


class AppReadOnlyError(AppConflictError):
    """A materialized published record cannot be changed in place."""


class AppNotFoundError(LookupError):
    """The requested application does not exist."""


@dataclass(frozen=True, slots=True)
class AppInput:
    name: str
    version: str
    description: str
    release_year: int
    model: str
    category: str
    author_name: str


@dataclass(frozen=True, slots=True)
class AppRecord:
    id: str
    name: str
    version: str
    description: str
    release_year: int
    model: str
    category: str
    author_id: str
    author_name: str
    publisher_uid: str
    publisher_email: str
    revision: int
    status: str = "STAGING"
    disk_media_ids: tuple[str | None, str | None, str | None, str | None] = (
        None,
        None,
        None,
        None,
    )
    cassette_media_id: str | None = None
    command_media_id: str | None = None
    basic_media_id: str | None = None
    screenshot_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MediaRecord:
    id: str
    app_id: str
    media_type: str
    slot: str
    filename: str
    description: str
    content_type: str
    object_path: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ScreenshotRecord:
    id: str
    app_id: str
    filename: str
    content_type: str
    object_path: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class AppDetail:
    app: AppRecord
    media: tuple[MediaRecord, ...]
    screenshots: tuple[ScreenshotRecord, ...]


@dataclass(frozen=True, slots=True)
class AppForm:
    values: Mapping[str, str]
    errors: Mapping[str, str]
    app_input: AppInput | None


class AppRepository(Protocol):
    def list_apps(self, identity: AdminIdentity) -> tuple[AppRecord, ...]: ...

    def create_app(
        self,
        *,
        identity: AdminIdentity,
        request_id: str,
        app_input: AppInput,
    ) -> AppRecord: ...

    def import_rpk(self, *, identity: AdminIdentity, package: ValidatedRpk) -> AppRecord: ...

    def get_app(self, identity: AdminIdentity, app_id: str) -> AppRecord | None: ...

    def get_app_detail(self, identity: AdminIdentity, app_id: str) -> AppDetail | None: ...

    def update_app(
        self,
        *,
        identity: AdminIdentity,
        app_id: str,
        expected_revision: int,
        app_input: AppInput,
    ) -> AppRecord: ...

    def publish_app(
        self,
        *,
        identity: AdminIdentity,
        app_id: str,
        expected_revision: int,
    ) -> AppRecord: ...

    def delete_app(
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
    ) -> AppRecord: ...

    def delete_media(
        self,
        *,
        identity: AdminIdentity,
        app_id: str,
        media_id: str,
        expected_revision: int,
    ) -> AppRecord: ...

    def upload_screenshot(
        self,
        *,
        identity: AdminIdentity,
        app_id: str,
        expected_revision: int,
        upload: ValidatedAssetUpload,
    ) -> AppRecord: ...

    def move_screenshot(
        self,
        *,
        identity: AdminIdentity,
        app_id: str,
        screenshot_id: str,
        expected_revision: int,
        direction: str,
    ) -> AppRecord: ...

    def delete_screenshot(
        self,
        *,
        identity: AdminIdentity,
        app_id: str,
        screenshot_id: str,
        expected_revision: int,
    ) -> AppRecord: ...

    def read_screenshot(
        self, identity: AdminIdentity, app_id: str, screenshot_id: str
    ) -> tuple[ScreenshotRecord, bytes] | None: ...


class FirestoreAppRepository:
    """Manage draft and published apps in Firestore."""

    def __init__(self, client: firestore.Client, object_store: AssetStore | None = None) -> None:
        self._client = client
        self._object_store = object_store

    def list_apps(self, identity: AdminIdentity) -> tuple[AppRecord, ...]:
        apps = tuple(
            _app_record(snapshot.id, _document_data(snapshot))
            for snapshot in self._client.collection(_APPS_COLLECTION).stream()
        )
        if not identity.is_administrator:
            apps = tuple(app for app in apps if app.publisher_uid == identity.uid)
        return tuple(sorted(apps, key=lambda app: (app.name.casefold(), app.id)))

    def get_app(self, identity: AdminIdentity, app_id: str) -> AppRecord | None:
        try:
            app_id = _app_document_id(app_id)
        except ValueError:
            return None
        snapshot = self._client.collection(_APPS_COLLECTION).document(app_id).get()
        if not snapshot.exists:
            return None
        app = _app_record(snapshot.id, _document_data(snapshot))
        _require_owner(identity, app)
        return app

    def get_app_detail(self, identity: AdminIdentity, app_id: str) -> AppDetail | None:
        app = self.get_app(identity, app_id)
        if app is None:
            return None
        media = tuple(self._load_media(media_id, app.id) for media_id in _ordered_media_ids(app))
        screenshots = tuple(
            self._load_screenshot(screenshot_id, app.id) for screenshot_id in app.screenshot_ids
        )
        return AppDetail(app=app, media=media, screenshots=screenshots)

    def create_app(
        self,
        *,
        identity: AdminIdentity,
        request_id: str,
        app_input: AppInput,
    ) -> AppRecord:
        app_id = _request_id(request_id)
        author_name = _normalized_author_name(app_input.author_name)
        author_id = _author_id(author_name)
        app = AppRecord(
            id=app_id,
            name=app_input.name,
            version=app_input.version,
            description=app_input.description,
            release_year=app_input.release_year,
            model=app_input.model,
            category=app_input.category,
            author_id=author_id,
            author_name=author_name,
            publisher_uid=identity.uid,
            publisher_email=identity.email,
            revision=1,
        )
        document = _app_document(app, request_id=app_id)
        digest = document["creationDigest"]
        app_reference = self._client.collection(_APPS_COLLECTION).document(app_id)
        author_reference = self._client.collection(_AUTHORS_COLLECTION).document(author_id)
        audit_reference = self._client.collection(_AUDIT_COLLECTION).document()
        transaction = self._client.transaction()

        @firestore.transactional
        def commit_app_record(transaction: Any) -> None:
            existing_app = app_reference.get(transaction=transaction)
            if existing_app.exists:
                existing = _document_data(existing_app)
                if (
                    existing.get("creationRequestId") == app_id
                    and existing.get("creationDigest") == digest
                    and existing.get("publisherUid") == identity.uid
                ):
                    return
                raise AppConflictError("Application request ID is already in use")

            _ensure_author(transaction, author_reference, author_name)

            transaction.create(app_reference, document)
            transaction.create(
                audit_reference,
                {
                    "schemaVersion": 1,
                    "eventType": "STAGED_APP_CREATED",
                    "status": "SUCCEEDED",
                    "actorUid": identity.uid,
                    "targetId": app_id,
                    "createdAt": firestore.SERVER_TIMESTAMP,
                },
            )

        commit_app_record(transaction)
        return app

    def import_rpk(self, *, identity: AdminIdentity, package: ValidatedRpk) -> AppRecord:
        """Create a complete isolated application from one validated legacy package."""

        app_id = _validated_app_id(package.app_id)
        object_store = self._object_store_or_error()
        author_name = _normalized_author_name(package.author_name)
        author_id = _author_id(author_name)
        prepared_media: list[tuple[str, str, str, str, ValidatedAssetUpload]] = []
        prepared_screenshots: list[tuple[str, str, ValidatedAssetUpload]] = []
        app = AppRecord(
            id=app_id,
            name=package.name,
            version=package.version,
            description=package.description,
            release_year=package.release_year,
            model=package.model,
            category=package.category,
            author_id=author_id,
            author_name=author_name,
            publisher_uid=identity.uid,
            publisher_email=identity.email,
            revision=1,
        )
        for item in package.media:
            media_type, _ = validate_media_slot(item.slot)
            if _media_id_for_slot(app, item.slot) is not None:
                raise ValueError("RPK contains duplicate media slots")
            media_id = new_asset_id()
            object_path = f"media/{app_id}/{media_id}/{item.upload.sha256}"
            prepared_media.append((media_id, media_type, item.slot, object_path, item.upload))
            app = _with_media_slot(app, item.slot, media_id)
        for upload in package.screenshots:
            if upload.extension is None or not upload.content_type.startswith("image/"):
                raise ValueError("Validated RPK screenshot format is missing")
            screenshot_id = new_asset_id()
            object_path = f"screenshots/{app_id}/{screenshot_id}/{upload.sha256}.{upload.extension}"
            prepared_screenshots.append((screenshot_id, object_path, upload))
        app = replace(
            app,
            screenshot_ids=tuple(item[0] for item in prepared_screenshots),
        )

        created_paths: list[str] = []
        try:
            for _, _, _, object_path, upload in prepared_media:
                if not object_store.put_verified(
                    path=object_path,
                    body=upload.body,
                    sha256=upload.sha256,
                    content_type=upload.content_type,
                ):
                    raise AppConflictError("Generated media identifier collided")
                created_paths.append(object_path)
            for _, object_path, upload in prepared_screenshots:
                if not object_store.put_verified(
                    path=object_path,
                    body=upload.body,
                    sha256=upload.sha256,
                    content_type=upload.content_type,
                ):
                    raise AppConflictError("Generated screenshot identifier collided")
                created_paths.append(object_path)

            app_reference = self._client.collection(_APPS_COLLECTION).document(app_id)
            author_reference = self._client.collection(_AUTHORS_COLLECTION).document(author_id)
            audit_reference = self._client.collection(_AUDIT_COLLECTION).document()
            transaction = self._client.transaction()

            @firestore.transactional
            def commit_rpk_import(transaction: Any) -> None:
                existing_app = app_reference.get(transaction=transaction)
                if existing_app.exists:
                    raise AppConflictError("A application already uses the RPK application ID")
                existing_author = author_reference.get(transaction=transaction)
                if existing_author.exists:
                    stored_author = _document_data(existing_author)
                    if stored_author.get("normalizedName") != author_name.casefold():
                        raise AppConflictError("Author identifier collision")

                if not existing_author.exists:
                    transaction.create(
                        author_reference,
                        {
                            "schemaVersion": 1,
                            "displayName": author_name,
                            "normalizedName": author_name.casefold(),
                            "createdAt": firestore.SERVER_TIMESTAMP,
                        },
                    )
                app_document = _app_document(app, request_id=app.id)
                app_document.update(
                    {
                        "creationSource": "RPK",
                        "sourcePackageSha256": package.package_sha256,
                        "sourcePackageSize": package.package_size,
                    }
                )
                transaction.create(app_reference, app_document)
                for media_id, media_type, slot, object_path, upload in prepared_media:
                    media_reference = self._client.collection(_MEDIA_COLLECTION).document(media_id)
                    transaction.create(
                        media_reference,
                        {
                            "schemaVersion": 1,
                            "appId": app.id,
                            "mediaType": media_type,
                            "slot": slot,
                            "filename": upload.filename,
                            "description": upload.description,
                            "contentType": upload.content_type,
                            "objectPath": object_path,
                            "size": upload.size,
                            "sha256": upload.sha256,
                            "publisherUid": identity.uid,
                            "createdAt": firestore.SERVER_TIMESTAMP,
                        },
                    )
                for position, (
                    screenshot_id,
                    object_path,
                    upload,
                ) in enumerate(prepared_screenshots):
                    screenshot_reference = self._client.collection(
                        _SCREENSHOTS_COLLECTION
                    ).document(screenshot_id)
                    transaction.create(
                        screenshot_reference,
                        {
                            "schemaVersion": 1,
                            "appId": app.id,
                            "filename": upload.filename,
                            "contentType": upload.content_type,
                            "objectPath": object_path,
                            "size": upload.size,
                            "sha256": upload.sha256,
                            "publisherUid": identity.uid,
                            "position": position,
                            "createdAt": firestore.SERVER_TIMESTAMP,
                        },
                    )
                transaction.create(
                    audit_reference,
                    {
                        "schemaVersion": 1,
                        "eventType": "STAGED_RPK_IMPORTED",
                        "status": "SUCCEEDED",
                        "actorUid": identity.uid,
                        "targetId": app.id,
                        "revision": app.revision,
                        "packageSha256": package.package_sha256,
                        "packageSize": package.package_size,
                        "mediaCount": len(prepared_media),
                        "screenshotCount": len(prepared_screenshots),
                        "createdAt": firestore.SERVER_TIMESTAMP,
                    },
                )

            commit_rpk_import(transaction)
        except Exception:
            for object_path in reversed(created_paths):
                object_store.delete(object_path)
            raise
        return app

    def update_app(
        self,
        *,
        identity: AdminIdentity,
        app_id: str,
        expected_revision: int,
        app_input: AppInput,
    ) -> AppRecord:
        try:
            app_id = _app_document_id(app_id)
        except ValueError as error:
            raise AppNotFoundError("Application does not exist") from error
        if expected_revision < 1:
            raise AppConflictError("Application revision is invalid")
        app_reference = self._client.collection(_APPS_COLLECTION).document(app_id)
        audit_reference = self._client.collection(_AUDIT_COLLECTION).document()
        transaction = self._client.transaction()

        @firestore.transactional
        def commit_app_record_update(transaction: Any) -> AppRecord:
            snapshot = app_reference.get(transaction=transaction)
            if not snapshot.exists:
                raise AppNotFoundError("Application does not exist")
            current = _app_record(snapshot.id, _document_data(snapshot))
            _require_owner(identity, current)
            _require_mutable(identity, current)
            if current.revision != expected_revision:
                raise AppConflictError(
                    "The application changed concurrently; reload before trying again"
                )

            author_name = _normalized_author_name(app_input.author_name)
            author_id = _author_id(author_name)
            author_reference = self._client.collection(_AUTHORS_COLLECTION).document(author_id)
            _ensure_author(transaction, author_reference, author_name)
            updated = replace(
                current,
                name=app_input.name,
                version=app_input.version,
                description=app_input.description,
                release_year=app_input.release_year,
                model=app_input.model,
                category=app_input.category,
                author_id=author_id,
                author_name=author_name,
                revision=current.revision + 1,
            )
            transaction.set(
                app_reference,
                {
                    **_mutable_app_document(updated),
                    "revision": updated.revision,
                    "updatedAt": firestore.SERVER_TIMESTAMP,
                },
                merge=True,
            )
            transaction.create(
                audit_reference,
                {
                    "schemaVersion": 1,
                    "eventType": (
                        "APP_UPDATED" if current.status == "PUBLISHED" else "STAGED_APP_UPDATED"
                    ),
                    "status": "SUCCEEDED",
                    "actorUid": identity.uid,
                    "targetId": current.id,
                    "previousRevision": current.revision,
                    "revision": updated.revision,
                    "createdAt": firestore.SERVER_TIMESTAMP,
                },
            )
            return updated

        return commit_app_record_update(transaction)

    def publish_app(
        self,
        *,
        identity: AdminIdentity,
        app_id: str,
        expected_revision: int,
    ) -> AppRecord:
        """Make one complete draft application visible to the public API atomically."""

        app_id = _existing_app_id(app_id)
        _require_positive_revision(expected_revision)
        app_reference = self._client.collection(_APPS_COLLECTION).document(app_id)
        audit_reference = self._client.collection(_AUDIT_COLLECTION).document()
        transaction = self._client.transaction()
        now_ms = time.time_ns() // 1_000_000

        @firestore.transactional
        def commit_publication(transaction: Any) -> AppRecord:
            current = _transaction_app(transaction, app_reference, identity, expected_revision)
            if current.status != "STAGING":
                raise AppConflictError("Only a application can be published")
            media_references = [
                self._client.collection(_MEDIA_COLLECTION).document(media_id)
                for media_id in _ordered_media_ids(current)
            ]
            screenshot_references = [
                self._client.collection(_SCREENSHOTS_COLLECTION).document(screenshot_id)
                for screenshot_id in current.screenshot_ids
            ]
            media_snapshots = [
                reference.get(transaction=transaction) for reference in media_references
            ]
            screenshot_snapshots = [
                reference.get(transaction=transaction) for reference in screenshot_references
            ]
            if not all(snapshot.exists for snapshot in (*media_snapshots, *screenshot_snapshots)):
                raise ValueError("Application asset references are incomplete")
            media = [
                _media_record(snapshot.id, _document_data(snapshot)) for snapshot in media_snapshots
            ]
            screenshots = [
                _screenshot_record(snapshot.id, _document_data(snapshot))
                for snapshot in screenshot_snapshots
            ]
            if any(item.app_id != current.id for item in (*media, *screenshots)):
                raise ValueError("Application asset reference belongs to another app")

            updated = replace(
                current,
                status="PUBLISHED",
                revision=current.revision + 1,
            )
            transaction.set(
                app_reference,
                {
                    "status": "PUBLISHED",
                    "revision": updated.revision,
                    "firstPublishedAtMs": now_ms,
                    "updatedAtMs": now_ms,
                    "firstPublishedAt": firestore.SERVER_TIMESTAMP,
                    "updatedAt": firestore.SERVER_TIMESTAMP,
                },
                merge=True,
            )
            transaction.create(
                audit_reference,
                {
                    "schemaVersion": 1,
                    "eventType": "APP_PUBLISHED",
                    "status": "SUCCEEDED",
                    "actorUid": identity.uid,
                    "targetId": current.id,
                    "previousRevision": current.revision,
                    "revision": updated.revision,
                    "createdAt": firestore.SERVER_TIMESTAMP,
                },
            )
            return updated

        return commit_publication(transaction)

    def upload_media(
        self,
        *,
        identity: AdminIdentity,
        app_id: str,
        expected_revision: int,
        slot: str,
        upload: ValidatedAssetUpload,
    ) -> AppRecord:
        app_id = _existing_app_id(app_id)
        _require_positive_revision(expected_revision)
        media_type, _ = validate_media_slot(slot)
        object_store = self._object_store_or_error()
        media_id = new_asset_id()
        object_path = f"media/{app_id}/{media_id}/{upload.sha256}"
        created = object_store.put_verified(
            path=object_path,
            body=upload.body,
            sha256=upload.sha256,
            content_type=upload.content_type,
        )
        if not created:
            raise AppConflictError("Generated media identifier collided")

        app_reference = self._client.collection(_APPS_COLLECTION).document(app_id)
        media_reference = self._client.collection(_MEDIA_COLLECTION).document(media_id)
        audit_reference = self._client.collection(_AUDIT_COLLECTION).document()
        transaction = self._client.transaction()
        replaced_object_path: str | None = None

        @firestore.transactional
        def commit_media_record(transaction: Any) -> AppRecord:
            nonlocal replaced_object_path
            current = _transaction_app(transaction, app_reference, identity, expected_revision)
            replaced_id = _media_id_for_slot(current, slot)
            replaced_reference = None
            if replaced_id is not None:
                replaced_reference = self._client.collection(_MEDIA_COLLECTION).document(
                    replaced_id
                )
                replaced_snapshot = replaced_reference.get(transaction=transaction)
                if not replaced_snapshot.exists:
                    raise ValueError("Application references missing media")
                replaced_media = _media_record(
                    replaced_snapshot.id, _document_data(replaced_snapshot)
                )
                if replaced_media.app_id != current.id or replaced_media.slot != slot:
                    raise ValueError("Application media reference is inconsistent")
                replaced_object_path = replaced_media.object_path

            updated = _with_media_slot(current, slot, media_id)
            updated = replace(updated, revision=current.revision + 1)
            transaction.create(
                media_reference,
                {
                    "schemaVersion": 1,
                    "appId": current.id,
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
            if replaced_reference is not None:
                transaction.delete(replaced_reference)
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
                {
                    "schemaVersion": 1,
                    "eventType": "STAGED_MEDIA_UPLOADED",
                    "status": "SUCCEEDED",
                    "actorUid": identity.uid,
                    "targetId": media_id,
                    "appId": current.id,
                    "slot": slot,
                    "replacedMediaId": replaced_id,
                    "previousRevision": current.revision,
                    "revision": updated.revision,
                    "createdAt": firestore.SERVER_TIMESTAMP,
                },
            )
            return updated

        try:
            updated = commit_media_record(transaction)
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
    ) -> AppRecord:
        app_id = _existing_app_id(app_id)
        media_id = _existing_asset_id(media_id, "Media")
        _require_positive_revision(expected_revision)
        object_store = self._object_store_or_error()
        app_reference = self._client.collection(_APPS_COLLECTION).document(app_id)
        media_reference = self._client.collection(_MEDIA_COLLECTION).document(media_id)
        audit_reference = self._client.collection(_AUDIT_COLLECTION).document()
        transaction = self._client.transaction()
        object_path = ""

        @firestore.transactional
        def commit_media_record_delete(transaction: Any) -> AppRecord:
            nonlocal object_path
            current = _transaction_app(transaction, app_reference, identity, expected_revision)
            snapshot = media_reference.get(transaction=transaction)
            if not snapshot.exists:
                raise AppNotFoundError("Media does not exist")
            media = _media_record(snapshot.id, _document_data(snapshot))
            if media.app_id != current.id or _media_id_for_slot(current, media.slot) != media.id:
                raise AppNotFoundError("Media is not attached to this app")
            object_path = media.object_path
            updated = replace(
                _with_media_slot(current, media.slot, None),
                revision=current.revision + 1,
            )
            transaction.delete(media_reference)
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
                {
                    "schemaVersion": 1,
                    "eventType": "STAGED_MEDIA_DELETED",
                    "status": "SUCCEEDED",
                    "actorUid": identity.uid,
                    "targetId": media.id,
                    "appId": current.id,
                    "slot": media.slot,
                    "previousRevision": current.revision,
                    "revision": updated.revision,
                    "createdAt": firestore.SERVER_TIMESTAMP,
                },
            )
            return updated

        updated = commit_media_record_delete(transaction)
        object_store.delete(object_path)
        return updated

    def upload_screenshot(
        self,
        *,
        identity: AdminIdentity,
        app_id: str,
        expected_revision: int,
        upload: ValidatedAssetUpload,
    ) -> AppRecord:
        app_id = _existing_app_id(app_id)
        _require_positive_revision(expected_revision)
        if upload.extension is None or not upload.content_type.startswith("image/"):
            raise ValueError("Validated screenshot format is missing")
        object_store = self._object_store_or_error()
        screenshot_id = new_asset_id()
        object_path = f"screenshots/{app_id}/{screenshot_id}/{upload.sha256}.{upload.extension}"
        created = object_store.put_verified(
            path=object_path,
            body=upload.body,
            sha256=upload.sha256,
            content_type=upload.content_type,
        )
        if not created:
            raise AppConflictError("Generated screenshot identifier collided")

        app_reference = self._client.collection(_APPS_COLLECTION).document(app_id)
        screenshot_reference = self._client.collection(_SCREENSHOTS_COLLECTION).document(
            screenshot_id
        )
        audit_reference = self._client.collection(_AUDIT_COLLECTION).document()
        transaction = self._client.transaction()

        @firestore.transactional
        def commit_screenshot_record(transaction: Any) -> AppRecord:
            current = _transaction_app(transaction, app_reference, identity, expected_revision)
            updated = replace(
                current,
                screenshot_ids=(*current.screenshot_ids, screenshot_id),
                revision=current.revision + 1,
            )
            transaction.create(
                screenshot_reference,
                {
                    "schemaVersion": 1,
                    "appId": current.id,
                    "filename": upload.filename,
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
                    "screenshotIds": list(updated.screenshot_ids),
                    "revision": updated.revision,
                    "updatedAt": firestore.SERVER_TIMESTAMP,
                },
                merge=True,
            )
            transaction.create(
                audit_reference,
                {
                    "schemaVersion": 1,
                    "eventType": "STAGED_SCREENSHOT_UPLOADED",
                    "status": "SUCCEEDED",
                    "actorUid": identity.uid,
                    "targetId": screenshot_id,
                    "appId": current.id,
                    "position": len(current.screenshot_ids),
                    "previousRevision": current.revision,
                    "revision": updated.revision,
                    "createdAt": firestore.SERVER_TIMESTAMP,
                },
            )
            return updated

        try:
            return commit_screenshot_record(transaction)
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
    ) -> AppRecord:
        app_id = _existing_app_id(app_id)
        screenshot_id = _existing_asset_id(screenshot_id, "Screenshot")
        _require_positive_revision(expected_revision)
        if direction not in {"up", "down"}:
            raise ValueError("Screenshot direction must be up or down")
        app_reference = self._client.collection(_APPS_COLLECTION).document(app_id)
        screenshot_reference = self._client.collection(_SCREENSHOTS_COLLECTION).document(
            screenshot_id
        )
        audit_reference = self._client.collection(_AUDIT_COLLECTION).document()
        transaction = self._client.transaction()

        @firestore.transactional
        def commit_screenshot_record_move(transaction: Any) -> AppRecord:
            current = _transaction_app(transaction, app_reference, identity, expected_revision)
            screenshot = screenshot_reference.get(transaction=transaction)
            if not screenshot.exists:
                raise AppNotFoundError("Screenshot does not exist")
            value = _screenshot_record(screenshot.id, _document_data(screenshot))
            if value.app_id != current.id or screenshot_id not in current.screenshot_ids:
                raise AppNotFoundError("Screenshot is not attached to this app")
            screenshot_ids = list(current.screenshot_ids)
            old_position = screenshot_ids.index(screenshot_id)
            new_position = old_position + (-1 if direction == "up" else 1)
            if not 0 <= new_position < len(screenshot_ids):
                raise AppConflictError("Screenshot is already at that boundary")
            screenshot_ids[old_position], screenshot_ids[new_position] = (
                screenshot_ids[new_position],
                screenshot_ids[old_position],
            )
            updated = replace(
                current,
                screenshot_ids=tuple(screenshot_ids),
                revision=current.revision + 1,
            )
            transaction.set(
                app_reference,
                {
                    "screenshotIds": screenshot_ids,
                    "revision": updated.revision,
                    "updatedAt": firestore.SERVER_TIMESTAMP,
                },
                merge=True,
            )
            transaction.create(
                audit_reference,
                {
                    "schemaVersion": 1,
                    "eventType": "STAGED_SCREENSHOT_MOVED",
                    "status": "SUCCEEDED",
                    "actorUid": identity.uid,
                    "targetId": screenshot_id,
                    "appId": current.id,
                    "previousPosition": old_position,
                    "position": new_position,
                    "previousRevision": current.revision,
                    "revision": updated.revision,
                    "createdAt": firestore.SERVER_TIMESTAMP,
                },
            )
            return updated

        return commit_screenshot_record_move(transaction)

    def delete_screenshot(
        self,
        *,
        identity: AdminIdentity,
        app_id: str,
        screenshot_id: str,
        expected_revision: int,
    ) -> AppRecord:
        app_id = _existing_app_id(app_id)
        screenshot_id = _existing_asset_id(screenshot_id, "Screenshot")
        _require_positive_revision(expected_revision)
        object_store = self._object_store_or_error()
        app_reference = self._client.collection(_APPS_COLLECTION).document(app_id)
        screenshot_reference = self._client.collection(_SCREENSHOTS_COLLECTION).document(
            screenshot_id
        )
        audit_reference = self._client.collection(_AUDIT_COLLECTION).document()
        transaction = self._client.transaction()
        object_path = ""

        @firestore.transactional
        def commit_screenshot_record_delete(transaction: Any) -> AppRecord:
            nonlocal object_path
            current = _transaction_app(transaction, app_reference, identity, expected_revision)
            snapshot = screenshot_reference.get(transaction=transaction)
            if not snapshot.exists:
                raise AppNotFoundError("Screenshot does not exist")
            screenshot = _screenshot_record(snapshot.id, _document_data(snapshot))
            if screenshot.app_id != current.id or screenshot.id not in current.screenshot_ids:
                raise AppNotFoundError("Screenshot is not attached to this app")
            object_path = screenshot.object_path
            position = current.screenshot_ids.index(screenshot.id)
            screenshot_ids = tuple(item for item in current.screenshot_ids if item != screenshot.id)
            updated = replace(
                current,
                screenshot_ids=screenshot_ids,
                revision=current.revision + 1,
            )
            transaction.delete(screenshot_reference)
            transaction.set(
                app_reference,
                {
                    "screenshotIds": list(screenshot_ids),
                    "revision": updated.revision,
                    "updatedAt": firestore.SERVER_TIMESTAMP,
                },
                merge=True,
            )
            transaction.create(
                audit_reference,
                {
                    "schemaVersion": 1,
                    "eventType": "STAGED_SCREENSHOT_DELETED",
                    "status": "SUCCEEDED",
                    "actorUid": identity.uid,
                    "targetId": screenshot.id,
                    "appId": current.id,
                    "previousPosition": position,
                    "previousRevision": current.revision,
                    "revision": updated.revision,
                    "createdAt": firestore.SERVER_TIMESTAMP,
                },
            )
            return updated

        updated = commit_screenshot_record_delete(transaction)
        object_store.delete(object_path)
        return updated

    def read_screenshot(
        self, identity: AdminIdentity, app_id: str, screenshot_id: str
    ) -> tuple[ScreenshotRecord, bytes] | None:
        app = self.get_app(identity, app_id)
        if app is None:
            return None
        try:
            screenshot_id = _existing_asset_id(screenshot_id, "Screenshot")
        except AppNotFoundError:
            return None
        if screenshot_id not in app.screenshot_ids:
            return None
        screenshot = self._load_screenshot(screenshot_id, app.id)
        body = self._object_store_or_error().read(screenshot.object_path)
        if len(body) != screenshot.size or hashlib.sha256(body).hexdigest() != screenshot.sha256:
            raise ValueError("Screenshot failed content verification")
        return screenshot, body

    def delete_app(
        self,
        *,
        identity: AdminIdentity,
        app_id: str,
        expected_revision: int,
    ) -> None:
        app_id = _existing_app_id(app_id)
        _require_positive_revision(expected_revision)
        app_reference = self._client.collection(_APPS_COLLECTION).document(app_id)
        audit_reference = self._client.collection(_AUDIT_COLLECTION).document()
        transaction = self._client.transaction()
        object_paths: list[str] = []

        @firestore.transactional
        def commit_app_record_delete(transaction: Any) -> None:
            current = _transaction_app(transaction, app_reference, identity, expected_revision)
            media_references = [
                self._client.collection(_MEDIA_COLLECTION).document(media_id)
                for media_id in _ordered_media_ids(current)
            ]
            screenshot_references = [
                self._client.collection(_SCREENSHOTS_COLLECTION).document(screenshot_id)
                for screenshot_id in current.screenshot_ids
            ]
            media_snapshots = [
                reference.get(transaction=transaction) for reference in media_references
            ]
            screenshot_snapshots = [
                reference.get(transaction=transaction) for reference in screenshot_references
            ]
            if not all(snapshot.exists for snapshot in (*media_snapshots, *screenshot_snapshots)):
                raise ValueError("Application asset references are incomplete")
            media = [
                _media_record(snapshot.id, _document_data(snapshot)) for snapshot in media_snapshots
            ]
            screenshots = [
                _screenshot_record(snapshot.id, _document_data(snapshot))
                for snapshot in screenshot_snapshots
            ]
            if any(item.app_id != current.id for item in (*media, *screenshots)):
                raise ValueError("Application asset reference belongs to another app")
            object_paths.extend(item.object_path for item in (*media, *screenshots))
            for reference in (*media_references, *screenshot_references):
                transaction.delete(reference)
            transaction.delete(app_reference)
            transaction.create(
                audit_reference,
                {
                    "schemaVersion": 1,
                    "eventType": "STAGED_APP_DELETED",
                    "status": "SUCCEEDED",
                    "actorUid": identity.uid,
                    "targetId": current.id,
                    "deletedRevision": current.revision,
                    "deletedMediaCount": len(media),
                    "deletedScreenshotCount": len(screenshots),
                    "createdAt": firestore.SERVER_TIMESTAMP,
                },
            )

        commit_app_record_delete(transaction)
        if object_paths:
            object_store = self._object_store_or_error()
            for object_path in object_paths:
                object_store.delete(object_path)

    def _load_media(self, media_id: str, app_id: str) -> MediaRecord:
        snapshot = self._client.collection(_MEDIA_COLLECTION).document(media_id).get()
        if not snapshot.exists:
            raise ValueError("Application references missing media")
        media = _media_record(snapshot.id, _document_data(snapshot))
        if media.app_id != app_id:
            raise ValueError("Media belongs to another app")
        return media

    def _load_screenshot(self, screenshot_id: str, app_id: str) -> ScreenshotRecord:
        snapshot = self._client.collection(_SCREENSHOTS_COLLECTION).document(screenshot_id).get()
        if not snapshot.exists:
            raise ValueError("Application references missing screenshot")
        screenshot = _screenshot_record(snapshot.id, _document_data(snapshot))
        if screenshot.app_id != app_id:
            raise ValueError("Screenshot belongs to another app")
        return screenshot

    def _object_store_or_error(self) -> AssetStore:
        if self._object_store is None:
            raise RuntimeError("Asset object storage is not configured")
        return self._object_store


def validate_app_form(form: Mapping[str, str], *, allow_existing_id: bool = False) -> AppForm:
    values = {
        "request_id": _form_value(form, "request_id"),
        "name": _form_value(form, "name"),
        "version": _form_value(form, "version"),
        "description": _form_value(form, "description", trim=False).strip(),
        "release_year": _form_value(form, "release_year"),
        "model": _form_value(form, "model"),
        "category": _form_value(form, "category"),
        "author_name": _form_value(form, "author_name"),
    }
    errors: dict[str, str] = {}
    _validate_required_length(values, errors, "name", "Name", 200)
    _validate_required_length(values, errors, "version", "Version", 64)
    _validate_required_length(values, errors, "description", "Description", 20_000)
    _validate_required_length(values, errors, "author_name", "Author", 200)

    try:
        release_year = int(values["release_year"])
        if not 0 <= release_year <= 9999:
            raise ValueError
    except ValueError:
        errors["release_year"] = "Release year must be an integer from 0 to 9999."
        release_year = 0
    if values["model"] not in APP_MODELS:
        errors["model"] = "Select a supported TRS-80 model."
    if values["category"] not in APP_CATEGORIES:
        errors["category"] = "Select a supported category."
    try:
        if allow_existing_id:
            _app_document_id(values["request_id"])
        else:
            _request_id(values["request_id"])
    except ValueError:
        errors["request_id"] = "The form request identifier is invalid; reload the form."

    app_input = None
    if not errors:
        app_input = AppInput(
            name=values["name"],
            version=values["version"],
            description=values["description"],
            release_year=release_year,
            model=values["model"],
            category=values["category"],
            author_name=_normalized_author_name(values["author_name"]),
        )
    return AppForm(values=values, errors=errors, app_input=app_input)


def new_app_request_id() -> str:
    return str(uuid.uuid4())


def new_asset_id() -> str:
    return str(uuid.uuid4())


def _app_document(app: AppRecord, *, request_id: str) -> dict[str, Any]:
    stable = {
        **_mutable_app_document(app),
        "publisherUid": app.publisher_uid,
        "publisherEmail": app.publisher_email,
        "mediaSlots": _media_slots_document(app),
        "screenshotIds": list(app.screenshot_ids),
        "status": app.status,
        "creationRequestId": request_id,
    }
    digest = hashlib.sha256(
        json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "schemaVersion": 1,
        **stable,
        "creationDigest": digest,
        "revision": app.revision,
        "createdAt": firestore.SERVER_TIMESTAMP,
        "updatedAt": firestore.SERVER_TIMESTAMP,
        "firstPublishedAt": None,
    }


def _mutable_app_document(app: AppRecord) -> dict[str, Any]:
    return {
        "name": app.name,
        "version": app.version,
        "description": app.description,
        "platform": "TRS80",
        "model": app.model,
        "categories": [app.category],
        "releaseYear": app.release_year,
        "authorId": app.author_id,
        "authorName": app.author_name,
    }


def _app_record(app_id: str, value: Mapping[str, Any]) -> AppRecord:
    app_id = _app_document_id(app_id)
    categories = value.get("categories")
    category = categories[0] if isinstance(categories, list) and categories else ""
    fields = {
        "name": value.get("name"),
        "version": value.get("version"),
        "description": value.get("description"),
        "model": value.get("model"),
        "author_id": value.get("authorId"),
        "author_name": value.get("authorName"),
        "publisher_uid": value.get("publisherUid"),
        "publisher_email": value.get("publisherEmail"),
    }
    if not all(isinstance(item, str) for item in fields.values()):
        raise ValueError("Application document has invalid string fields")
    release_year = value.get("releaseYear")
    if isinstance(release_year, bool) or not isinstance(release_year, int):
        raise ValueError("Application document has an invalid release year")
    revision = value.get("revision", 1)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("Application document has an invalid revision")
    status = value.get("status", "STAGING")
    if status not in {"STAGING", "PUBLISHED"}:
        raise ValueError("Application document has an invalid status")
    media_slots = value.get(
        "mediaSlots",
        {
            "disks": [None, None, None, None],
            "cassette": None,
            "command": None,
            "basic": None,
        },
    )
    if not isinstance(media_slots, Mapping):
        raise ValueError("Application media slots are invalid")
    disks = media_slots.get("disks")
    if not isinstance(disks, list) or len(disks) != 4:
        raise ValueError("Application must contain four disk slots")
    disk_media_ids = tuple(_optional_asset_id(item, "media") for item in disks)
    screenshot_values = value.get("screenshotIds", [])
    if not isinstance(screenshot_values, list):
        raise ValueError("Application screenshot order is invalid")
    screenshot_ids = tuple(_optional_asset_id(item, "screenshot") for item in screenshot_values)
    if any(item is None for item in screenshot_ids):
        raise ValueError("Application screenshot IDs cannot be null")
    if len(set(screenshot_ids)) != len(screenshot_ids):
        raise ValueError("Application screenshot IDs must be unique")
    return AppRecord(
        id=app_id,
        category=category,
        release_year=release_year,
        revision=revision,
        status=status,
        disk_media_ids=disk_media_ids,  # type: ignore[arg-type]
        cassette_media_id=_optional_asset_id(media_slots.get("cassette"), "media"),
        command_media_id=_optional_asset_id(media_slots.get("command"), "media"),
        basic_media_id=_optional_asset_id(media_slots.get("basic"), "media"),
        screenshot_ids=screenshot_ids,  # type: ignore[arg-type]
        **fields,
    )


def _media_record(media_id: str, value: Mapping[str, Any]) -> MediaRecord:
    media_id = _existing_asset_id(media_id, "Media")
    string_fields = {
        "app_id": value.get("appId"),
        "media_type": value.get("mediaType"),
        "slot": value.get("slot"),
        "filename": value.get("filename"),
        "description": value.get("description"),
        "content_type": value.get("contentType"),
        "object_path": value.get("objectPath"),
        "sha256": value.get("sha256"),
    }
    if not all(isinstance(item, str) for item in string_fields.values()):
        raise ValueError("Media document has invalid string fields")
    media_type, _ = validate_media_slot(string_fields["slot"])
    if string_fields["media_type"] != media_type:
        raise ValueError("Media type does not match its slot")
    if string_fields["content_type"] != "application/octet-stream":
        raise ValueError("Media content type is invalid")
    size = _asset_size(value.get("size"))
    _validate_asset_object_path(
        kind="media",
        app_id=string_fields["app_id"],
        asset_id=media_id,
        digest=string_fields["sha256"],
        extension=None,
        actual=string_fields["object_path"],
    )
    return MediaRecord(id=media_id, size=size, **string_fields)


def _screenshot_record(screenshot_id: str, value: Mapping[str, Any]) -> ScreenshotRecord:
    screenshot_id = _existing_asset_id(screenshot_id, "Screenshot")
    string_fields = {
        "app_id": value.get("appId"),
        "filename": value.get("filename"),
        "content_type": value.get("contentType"),
        "object_path": value.get("objectPath"),
        "sha256": value.get("sha256"),
    }
    if not all(isinstance(item, str) for item in string_fields.values()):
        raise ValueError("Screenshot document has invalid string fields")
    extensions = {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/gif": "gif",
        "image/webp": "webp",
    }
    try:
        extension = extensions[string_fields["content_type"]]
    except KeyError as error:
        raise ValueError("Screenshot content type is invalid") from error
    size = _asset_size(value.get("size"))
    try:
        _validate_asset_object_path(
            kind="screenshots",
            app_id=string_fields["app_id"],
            asset_id=screenshot_id,
            digest=string_fields["sha256"],
            extension=extension,
            actual=string_fields["object_path"],
        )
    except ValueError:
        # Imported App Engine screenshots predate extension-bearing object paths.
        _validate_asset_object_path(
            kind="screenshots",
            app_id=string_fields["app_id"],
            asset_id=screenshot_id,
            digest=string_fields["sha256"],
            extension=None,
            actual=string_fields["object_path"],
        )
    return ScreenshotRecord(id=screenshot_id, size=size, **string_fields)


def _transaction_app(
    transaction: Any,
    app_reference: Any,
    identity: AdminIdentity,
    expected_revision: int,
) -> AppRecord:
    snapshot = app_reference.get(transaction=transaction)
    if not snapshot.exists:
        raise AppNotFoundError("Application does not exist")
    current = _app_record(snapshot.id, _document_data(snapshot))
    _require_owner(identity, current)
    _require_mutable(identity, current)
    if current.revision != expected_revision:
        raise AppConflictError("The application changed concurrently; reload before trying again")
    return current


def _ordered_media_ids(app: AppRecord) -> tuple[str, ...]:
    values = (
        *app.disk_media_ids,
        app.cassette_media_id,
        app.command_media_id,
        app.basic_media_id,
    )
    result = tuple(item for item in values if item is not None)
    if len(result) != len(set(result)):
        raise ValueError("Media IDs must be unique across slots")
    return result


def _media_id_for_slot(app: AppRecord, slot: str) -> str | None:
    _, position = validate_media_slot(slot)
    if position is not None:
        return app.disk_media_ids[position]
    return {
        "cassette": app.cassette_media_id,
        "command": app.command_media_id,
        "basic": app.basic_media_id,
    }[slot]


def _with_media_slot(app: AppRecord, slot: str, media_id: str | None) -> AppRecord:
    _, position = validate_media_slot(slot)
    if position is not None:
        disks = list(app.disk_media_ids)
        disks[position] = media_id
        return replace(app, disk_media_ids=tuple(disks))  # type: ignore[arg-type]
    if slot == "cassette":
        return replace(app, cassette_media_id=media_id)
    if slot == "command":
        return replace(app, command_media_id=media_id)
    return replace(app, basic_media_id=media_id)


def _media_slots_document(app: AppRecord) -> dict[str, object]:
    return {
        "disks": list(app.disk_media_ids),
        "cassette": app.cassette_media_id,
        "command": app.command_media_id,
        "basic": app.basic_media_id,
    }


def _existing_app_id(value: str) -> str:
    try:
        return _app_document_id(value)
    except ValueError as error:
        raise AppNotFoundError("Application does not exist") from error


def _existing_asset_id(value: str, label: str) -> str:
    try:
        return _app_document_id(value)
    except ValueError as error:
        raise AppNotFoundError(f"{label} does not exist") from error


def _optional_asset_id(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label.title()} ID is invalid")
    try:
        return _app_document_id(value)
    except ValueError as error:
        raise ValueError(f"{label.title()} ID is invalid") from error


def _require_positive_revision(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise AppConflictError("Application revision is invalid")


def _asset_size(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("Asset size is invalid")
    return value


def _validate_asset_object_path(
    *,
    kind: str,
    app_id: str,
    asset_id: str,
    digest: str,
    extension: str | None,
    actual: str,
) -> None:
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError("Asset SHA-256 is invalid")
    suffix = digest if extension is None else f"{digest}.{extension}"
    expected = f"{kind}/{app_id}/{asset_id}/{suffix}"
    if actual != expected:
        raise ValueError("Asset object path is invalid")


def _ensure_author(transaction: Any, reference: Any, author_name: str) -> None:
    existing_author = reference.get(transaction=transaction)
    if existing_author.exists:
        stored_author = _document_data(existing_author)
        if stored_author.get("normalizedName") != author_name.casefold():
            raise AppConflictError("Author identifier collision")
        return
    transaction.create(
        reference,
        {
            "schemaVersion": 1,
            "displayName": author_name,
            "normalizedName": author_name.casefold(),
            "createdAt": firestore.SERVER_TIMESTAMP,
        },
    )


def _require_owner(identity: AdminIdentity, app: AppRecord) -> None:
    if not identity.is_administrator and app.publisher_uid != identity.uid:
        raise AppAuthorizationError("Publisher does not own this application")


def _require_mutable(identity: AdminIdentity, app: AppRecord) -> None:
    if app.status == "PUBLISHED" and not identity.is_administrator:
        raise AppReadOnlyError("Only administrators can change a published app")
    if app.status not in {"STAGING", "PUBLISHED"}:
        raise AppReadOnlyError("This app record is not directly editable")


def _request_id(value: str) -> str:
    parsed = uuid.UUID(value)
    if parsed.version != 4 or str(parsed) != value:
        raise ValueError("Application request ID must be a normalized UUID4")
    return value


def _validated_app_id(value: str) -> str:
    parsed = uuid.UUID(value)
    if str(parsed) != value:
        raise ValueError("Application ID must be a lowercase UUID")
    return value


def _app_document_id(value: str) -> str:
    if not value or value in {".", ".."} or "/" in value:
        raise ValueError("Application document ID is invalid")
    if len(value.encode("utf-8")) > 1_500:
        raise ValueError("Application document ID is too long")
    if value.startswith("__") and value.endswith("__"):
        raise ValueError("Application document ID uses a reserved form")
    return value


def _normalized_author_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _author_id(name: str) -> str:
    digest = hashlib.sha256(name.casefold().encode()).hexdigest()
    return f"new-{digest[:32]}"


def _form_value(form: Mapping[str, str], name: str, *, trim: bool = True) -> str:
    value = form.get(name, "")
    if not isinstance(value, str):
        return ""
    return value.strip() if trim else value


def _validate_required_length(
    values: Mapping[str, str],
    errors: dict[str, str],
    name: str,
    label: str,
    maximum: int,
) -> None:
    value = values[name]
    if not value:
        errors[name] = f"{label} is required."
    elif len(value) > maximum:
        errors[name] = f"{label} must not exceed {maximum} characters."


def _document_data(snapshot: Any) -> Mapping[str, Any]:
    value = snapshot.to_dict()
    if not isinstance(value, dict):
        raise ValueError("Application document is malformed")
    return value

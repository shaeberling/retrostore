"""Direct Firestore catalog and Cloud Storage object access."""

import hashlib
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, Protocol

from google.api_core.exceptions import NotFound
from google.cloud import firestore, storage

from retrostore.catalog.models import (
    CatalogApp,
    CatalogMedia,
    CatalogScreenshot,
    ObjectMetadata,
)

_COLLECTIONS = frozenset({"apps", "media", "screenshots"})


class DocumentSnapshot(Protocol):
    id: str
    exists: bool

    def to_dict(self) -> dict[str, Any] | None: ...


class FirestoreCatalogRepository:
    """Read the small catalog without snapshots or working copies."""

    def __init__(self, client: firestore.Client) -> None:
        self._client = client

    def list_apps(self) -> tuple[CatalogApp, ...]:
        return tuple(
            _app(snapshot.id, _document_data(snapshot))
            for snapshot in self._client.collection("apps").stream()
            if _is_published(snapshot)
        )

    def get_app(self, app_id: str) -> CatalogApp | None:
        if not _valid_document_id(app_id):
            return None
        snapshot = self._client.collection("apps").document(app_id).get()
        if not snapshot.exists:
            return None
        value = _document_data(snapshot)
        if value.get("status") != "PUBLISHED":
            return None
        return _app(snapshot.id, value)

    def get_media(self, media_ids: Iterable[str], *, app_id: str) -> Mapping[str, CatalogMedia]:
        values = self._get_documents("media", media_ids)
        result = {media_id: _media(media_id, document) for media_id, document in values.items()}
        if any(value.app_id != app_id for value in result.values()):
            raise ValueError("Catalog media belongs to another app")
        return result

    def list_media(self) -> Mapping[str, CatalogMedia]:
        return {
            snapshot.id: _media(snapshot.id, _document_data(snapshot))
            for snapshot in self._client.collection("media").stream()
        }

    def get_screenshots(
        self, screenshot_ids: Iterable[str], *, app_id: str
    ) -> Mapping[str, CatalogScreenshot]:
        values = self._get_documents("screenshots", screenshot_ids)
        result = {
            screenshot_id: _screenshot(screenshot_id, document)
            for screenshot_id, document in values.items()
        }
        if any(value.app_id != app_id for value in result.values()):
            raise ValueError("Catalog screenshot belongs to another app")
        return result

    def list_screenshots(self) -> Mapping[str, CatalogScreenshot]:
        return {
            snapshot.id: _screenshot(snapshot.id, _document_data(snapshot))
            for snapshot in self._client.collection("screenshots").stream()
        }

    def get_screenshot(self, screenshot_id: str) -> CatalogScreenshot | None:
        if not _valid_document_id(screenshot_id):
            return None
        snapshot = self._client.collection("screenshots").document(screenshot_id).get()
        if not snapshot.exists:
            return None
        return _screenshot(snapshot.id, _document_data(snapshot))

    def _get_documents(
        self, collection: str, document_ids: Iterable[str]
    ) -> dict[str, Mapping[str, Any]]:
        if collection not in _COLLECTIONS:
            raise ValueError("Unknown catalog collection")
        ids = tuple(dict.fromkeys(document_ids))
        if any(not _valid_document_id(value) for value in ids):
            raise ValueError("Catalog catalog contains an invalid reference")
        references = [
            self._client.collection(collection).document(document_id) for document_id in ids
        ]
        snapshots = tuple(self._client.get_all(references)) if references else ()
        result = {
            snapshot.id: _document_data(snapshot) for snapshot in snapshots if snapshot.exists
        }
        if set(result) != set(ids):
            raise ValueError(f"Catalog catalog references missing {collection}")
        return result


class CloudObjectReader:
    """Read one immutable object or byte range only when a response needs it."""

    def __init__(self, bucket: storage.Bucket) -> None:
        self._bucket = bucket

    def read(
        self,
        descriptor: ObjectMetadata,
        start: int = 0,
        length: int | None = None,
    ) -> bytes:
        if start < 0 or (length is not None and length < 0):
            raise ValueError("Catalog object range is invalid")
        if start >= descriptor.size:
            return b""
        try:
            if start == 0 and length is None:
                body = bytes(self._bucket.blob(descriptor.path).download_as_bytes(checksum="auto"))
                if len(body) != descriptor.size:
                    raise ValueError("Catalog object size does not match metadata")
                if hashlib.sha256(body).hexdigest() != descriptor.sha256:
                    raise ValueError("Catalog object digest does not match metadata")
                return body

            end = descriptor.size - 1
            if length is not None:
                end = min(end, start + length - 1)
            if end < start:
                return b""
            return bytes(
                self._bucket.blob(descriptor.path).download_as_bytes(
                    start=start,
                    end=end,
                    checksum=None,
                )
            )
        except NotFound as error:
            raise ValueError(f"Catalog object is missing: {descriptor.path}") from error


def create_google_catalog(
    *, project: str, database: str, bucket: str
) -> tuple[FirestoreCatalogRepository, CloudObjectReader]:
    """Construct lazy catalog adapters without performing catalog reads."""

    if not project or not database or not bucket:
        raise ValueError("Catalog catalog resources must be explicit")
    if database == "(default)":
        raise ValueError("Catalog must not use the legacy default database")
    client = firestore.Client(project=project, database=database)
    object_bucket = storage.Client(project=project).bucket(bucket)
    return FirestoreCatalogRepository(client), CloudObjectReader(object_bucket)


def _is_published(snapshot: DocumentSnapshot) -> bool:
    return snapshot.exists and _document_data(snapshot).get("status") == "PUBLISHED"


def _app(app_id: str, value: Mapping[str, Any]) -> CatalogApp:
    _schema(value, "app")
    source_author_id = (
        value.get("sourceAuthorId") if "sourceAuthorId" in value else value.get("authorId")
    )
    return CatalogApp.from_dict(
        {
            "id": app_id,
            "name": _string(value, "name"),
            "version": _string(value, "version"),
            "description": _string(value, "description"),
            "release_year": _integer(value, "releaseYear"),
            "platform": _required_string(value, "platform"),
            "model": _required_string(value, "model"),
            "categories": _string_list(value, "categories"),
            "author_id": _optional_string(source_author_id, "sourceAuthorId"),
            "author_name": _string(value, "authorName"),
            "publisher_email": _string(value, "publisherEmail"),
            "first_published_at_ms": _timestamp_ms(value, "firstPublishedAtMs", "firstPublishedAt"),
            "updated_at_ms": _timestamp_ms(value, "updatedAtMs", "updatedAt"),
            "media_slots": _media_slots(value),
            "screenshot_ids": _string_list(value, "screenshotIds"),
        }
    )


def _media(media_id: str, value: Mapping[str, Any]) -> CatalogMedia:
    _schema(value, "media")
    if value.get("contentType") != "application/octet-stream":
        raise ValueError("Catalog media content type is invalid")
    return CatalogMedia.from_dict(
        {
            "id": media_id,
            "app_id": _required_string(value, "appId"),
            "media_type": _required_string(value, "mediaType"),
            "filename": _string(value, "filename"),
            "description": _string(value, "description"),
            "upload_time_ms": _timestamp_ms(value, "uploadTimeMs", "createdAt"),
            **_object(value),
        }
    )


def _screenshot(screenshot_id: str, value: Mapping[str, Any]) -> CatalogScreenshot:
    _schema(value, "screenshot")
    legacy_url = value.get("legacyServingUrl")
    if legacy_url is not None and not isinstance(legacy_url, str):
        raise ValueError("Catalog screenshot legacy URL is invalid")
    return CatalogScreenshot.from_dict(
        {
            "id": screenshot_id,
            "app_id": _required_string(value, "appId"),
            "filename": _string(value, "filename"),
            "content_type": _required_string(value, "contentType"),
            "upload_time_ms": _timestamp_ms(value, "uploadTimeMs", "createdAt"),
            "legacy_serving_url": legacy_url,
            **_object(value),
        }
    )


def _object(value: Mapping[str, Any]) -> dict[str, str | int]:
    return {
        "object_path": _required_string(value, "objectPath"),
        "size": _integer(value, "size"),
        "sha256": _required_string(value, "sha256"),
    }


def _media_slots(value: Mapping[str, Any]) -> Mapping[str, Any]:
    slots = value.get("mediaSlots")
    if not isinstance(slots, Mapping):
        raise ValueError("Catalog app media slots are invalid")
    return {
        "disks": slots.get("disks"),
        "cassette": slots.get("cassette"),
        "command": slots.get("command"),
        "basic": slots.get("basic"),
    }


def _schema(value: Mapping[str, Any], label: str) -> None:
    if value.get("schemaVersion") != 1:
        raise ValueError(f"Catalog {label} schema is unsupported")


def _document_data(snapshot: DocumentSnapshot) -> Mapping[str, Any]:
    value = snapshot.to_dict()
    if not isinstance(value, dict):
        raise ValueError("Catalog Firestore document is malformed")
    return value


def _valid_document_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value not in {".", ".."}
        and "/" not in value
        and len(value.encode("utf-8")) <= 1_500
        and not (value.startswith("__") and value.endswith("__"))
    )


def _required_string(value: Mapping[str, Any], field: str) -> str:
    result = value.get(field)
    if not isinstance(result, str) or not result:
        raise ValueError(f"Catalog field {field} must be a non-empty string")
    return result


def _string(value: Mapping[str, Any], field: str) -> str:
    result = value.get(field)
    if not isinstance(result, str):
        raise ValueError(f"Catalog field {field} must be a string")
    return result


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Catalog field {field} must be a string or null")
    return value


def _integer(value: Mapping[str, Any], field: str) -> int:
    result = value.get(field)
    if isinstance(result, bool) or not isinstance(result, int):
        raise ValueError(f"Catalog field {field} must be an integer")
    return result


def _string_list(value: Mapping[str, Any], field: str) -> list[str]:
    result = value.get(field)
    if not isinstance(result, list) or not all(isinstance(item, str) for item in result):
        raise ValueError(f"Catalog field {field} must be a string list")
    return result


def _timestamp_ms(value: Mapping[str, Any], integer_field: str, timestamp_field: str) -> int:
    result = value.get(integer_field)
    if isinstance(result, int) and not isinstance(result, bool) and result >= 0:
        return result
    timestamp = value.get(timestamp_field)
    if isinstance(timestamp, datetime):
        return max(0, int(timestamp.timestamp() * 1_000))
    raise ValueError(f"Catalog timestamp {integer_field} is missing")

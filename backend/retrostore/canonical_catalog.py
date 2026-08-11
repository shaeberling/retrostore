"""Canonical top-level Firestore catalog used directly by serving code."""

import hashlib
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, Protocol

from google.api_core.exceptions import NotFound
from google.cloud import firestore, storage

from retrostore.mirror.catalog import (
    NormalizedApp,
    NormalizedMedia,
    NormalizedScreenshot,
    ObjectDescriptor,
)

_COLLECTIONS = frozenset({"apps", "media", "screenshots"})


class DocumentSnapshot(Protocol):
    id: str
    exists: bool

    def to_dict(self) -> dict[str, Any] | None: ...


class CanonicalCatalogRepository:
    """Read the small canonical catalog without snapshots or working copies."""

    def __init__(self, client: firestore.Client) -> None:
        self._client = client

    def list_apps(self) -> tuple[NormalizedApp, ...]:
        return tuple(
            _app(snapshot.id, _document_data(snapshot))
            for snapshot in self._client.collection("apps").stream()
            if _is_published(snapshot)
        )

    def get_app(self, app_id: str) -> NormalizedApp | None:
        if not _valid_document_id(app_id):
            return None
        snapshot = self._client.collection("apps").document(app_id).get()
        if not snapshot.exists:
            return None
        value = _document_data(snapshot)
        if value.get("status") != "PUBLISHED":
            return None
        return _app(snapshot.id, value)

    def get_media(
        self, media_ids: Iterable[str], *, app_id: str
    ) -> Mapping[str, NormalizedMedia]:
        values = self._get_documents("media", media_ids)
        result = {
            media_id: _media(media_id, document)
            for media_id, document in values.items()
        }
        if any(value.app_id != app_id for value in result.values()):
            raise ValueError("Canonical media belongs to another app")
        return result

    def list_media(self) -> Mapping[str, NormalizedMedia]:
        return {
            snapshot.id: _media(snapshot.id, _document_data(snapshot))
            for snapshot in self._client.collection("media").stream()
        }

    def get_screenshots(
        self, screenshot_ids: Iterable[str], *, app_id: str
    ) -> Mapping[str, NormalizedScreenshot]:
        values = self._get_documents("screenshots", screenshot_ids)
        result = {
            screenshot_id: _screenshot(screenshot_id, document)
            for screenshot_id, document in values.items()
        }
        if any(value.app_id != app_id for value in result.values()):
            raise ValueError("Canonical screenshot belongs to another app")
        return result

    def list_screenshots(self) -> Mapping[str, NormalizedScreenshot]:
        return {
            snapshot.id: _screenshot(snapshot.id, _document_data(snapshot))
            for snapshot in self._client.collection("screenshots").stream()
        }

    def get_screenshot(self, screenshot_id: str) -> NormalizedScreenshot | None:
        if not _valid_document_id(screenshot_id):
            return None
        snapshot = (
            self._client.collection("screenshots").document(screenshot_id).get()
        )
        if not snapshot.exists:
            return None
        return _screenshot(snapshot.id, _document_data(snapshot))

    def _get_documents(
        self, collection: str, document_ids: Iterable[str]
    ) -> dict[str, Mapping[str, Any]]:
        if collection not in _COLLECTIONS:
            raise ValueError("Unknown canonical catalog collection")
        ids = tuple(dict.fromkeys(document_ids))
        if any(not _valid_document_id(value) for value in ids):
            raise ValueError("Canonical catalog contains an invalid reference")
        references = [
            self._client.collection(collection).document(document_id)
            for document_id in ids
        ]
        snapshots = tuple(self._client.get_all(references)) if references else ()
        result = {
            snapshot.id: _document_data(snapshot)
            for snapshot in snapshots
            if snapshot.exists
        }
        if set(result) != set(ids):
            raise ValueError(f"Canonical catalog references missing {collection}")
        return result


class VerifiedCloudObjectReader:
    """Read one immutable object or byte range only when a response needs it."""

    def __init__(self, bucket: storage.Bucket) -> None:
        self._bucket = bucket

    def read(
        self,
        descriptor: ObjectDescriptor,
        start: int = 0,
        length: int | None = None,
    ) -> bytes:
        if start < 0 or (length is not None and length < 0):
            raise ValueError("Canonical object range is invalid")
        if start >= descriptor.size:
            return b""
        try:
            if start == 0 and length is None:
                body = bytes(
                    self._bucket.blob(descriptor.path).download_as_bytes(
                        checksum="auto"
                    )
                )
                if len(body) != descriptor.size:
                    raise ValueError("Canonical object size does not match metadata")
                if hashlib.sha256(body).hexdigest() != descriptor.sha256:
                    raise ValueError("Canonical object digest does not match metadata")
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
            raise ValueError(f"Canonical object is missing: {descriptor.path}") from error


def google_canonical_catalog(
    *, project: str, database: str, bucket: str
) -> tuple[CanonicalCatalogRepository, VerifiedCloudObjectReader]:
    """Construct lazy canonical adapters without performing catalog reads."""

    if not project or not database or not bucket:
        raise ValueError("Canonical catalog resources must be explicit")
    if database == "(default)":
        raise ValueError("Canonical catalog must not use the legacy default database")
    client = firestore.Client(project=project, database=database)
    object_bucket = storage.Client(project=project).bucket(bucket)
    return CanonicalCatalogRepository(client), VerifiedCloudObjectReader(object_bucket)


def _is_published(snapshot: DocumentSnapshot) -> bool:
    return snapshot.exists and _document_data(snapshot).get("status") == "PUBLISHED"


def _app(app_id: str, value: Mapping[str, Any]) -> NormalizedApp:
    _schema(value, "app")
    source_author_id = (
        value.get("sourceAuthorId")
        if "sourceAuthorId" in value
        else value.get("authorId")
    )
    return NormalizedApp.from_dict(
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
            "first_published_at_ms": _timestamp_ms(
                value, "firstPublishedAtMs", "firstPublishedAt"
            ),
            "updated_at_ms": _timestamp_ms(value, "updatedAtMs", "updatedAt"),
            "media_slots": _media_slots(value),
            "screenshot_ids": _string_list(value, "screenshotIds"),
        }
    )


def _media(media_id: str, value: Mapping[str, Any]) -> NormalizedMedia:
    _schema(value, "media")
    if value.get("contentType") != "application/octet-stream":
        raise ValueError("Canonical media content type is invalid")
    return NormalizedMedia.from_dict(
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


def _screenshot(screenshot_id: str, value: Mapping[str, Any]) -> NormalizedScreenshot:
    _schema(value, "screenshot")
    legacy_url = value.get("legacyServingUrl")
    if legacy_url is not None and not isinstance(legacy_url, str):
        raise ValueError("Canonical screenshot legacy URL is invalid")
    return NormalizedScreenshot.from_dict(
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
        raise ValueError("Canonical app media slots are invalid")
    return {
        "disks": slots.get("disks"),
        "cassette": slots.get("cassette"),
        "command": slots.get("command"),
        "basic": slots.get("basic"),
    }


def _schema(value: Mapping[str, Any], label: str) -> None:
    if value.get("schemaVersion") != 1:
        raise ValueError(f"Canonical {label} schema is unsupported")


def _document_data(snapshot: DocumentSnapshot) -> Mapping[str, Any]:
    value = snapshot.to_dict()
    if not isinstance(value, dict):
        raise ValueError("Canonical Firestore document is malformed")
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
        raise ValueError(f"Canonical field {field} must be a non-empty string")
    return result


def _string(value: Mapping[str, Any], field: str) -> str:
    result = value.get(field)
    if not isinstance(result, str):
        raise ValueError(f"Canonical field {field} must be a string")
    return result


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Canonical field {field} must be a string or null")
    return value


def _integer(value: Mapping[str, Any], field: str) -> int:
    result = value.get(field)
    if isinstance(result, bool) or not isinstance(result, int):
        raise ValueError(f"Canonical field {field} must be an integer")
    return result


def _string_list(value: Mapping[str, Any], field: str) -> list[str]:
    result = value.get(field)
    if not isinstance(result, list) or not all(isinstance(item, str) for item in result):
        raise ValueError(f"Canonical field {field} must be a string list")
    return result


def _timestamp_ms(
    value: Mapping[str, Any], integer_field: str, timestamp_field: str
) -> int:
    result = value.get(integer_field)
    if isinstance(result, int) and not isinstance(result, bool) and result >= 0:
        return result
    timestamp = value.get(timestamp_field)
    if isinstance(timestamp, datetime):
        return max(0, int(timestamp.timestamp() * 1_000))
    raise ValueError(f"Canonical timestamp {integer_field} is missing")

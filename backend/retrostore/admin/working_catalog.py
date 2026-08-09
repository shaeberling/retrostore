"""Deterministic bridge between published mirrors and the admin working schema."""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

from retrostore.mirror.catalog import CatalogMirror, ObjectReader
from retrostore.mirror.persistence import CatalogSnapshot

_COLLECTIONS = ("apps", "authors", "media", "screenshots")
_MEDIA_TYPES = {
    "disk-1": "DISK",
    "disk-2": "DISK",
    "disk-3": "DISK",
    "disk-4": "DISK",
    "cassette": "CASSETTE",
    "command": "COMMAND",
    "basic": "BASIC",
}


@dataclass(frozen=True, slots=True)
class WorkingCatalogMaterialization:
    id: str
    source: Mapping[str, str]
    collections: Mapping[str, Mapping[str, Mapping[str, Any]]]
    manifest_sha256: str

    @property
    def counts(self) -> Mapping[str, int]:
        return MappingProxyType(
            {name: len(self.collections[name]) for name in _COLLECTIONS}
        )


def build_working_catalog_materialization(
    mirror: CatalogMirror, source_snapshot: CatalogSnapshot
) -> WorkingCatalogMaterialization:
    """Build immutable top-level documents without assigning Firebase ownership."""

    if source_snapshot.metadata.get("source") != mirror.to_dict()["source"]:
        raise ValueError("Working catalog source snapshot does not match the mirror")
    slot_by_media_id = _media_slots(mirror)
    if set(slot_by_media_id) != set(mirror.media):
        raise ValueError("Published mirror contains unreferenced media records")
    referenced_screenshots = {
        screenshot_id for app in mirror.apps for screenshot_id in app.screenshot_ids
    }
    if referenced_screenshots != set(mirror.screenshots):
        raise ValueError("Published mirror contains unreferenced screenshot records")

    source = MappingProxyType(
        {
            "projectId": mirror.source_project_id,
            "exportedAt": mirror.exported_at,
            "highWaterMark": mirror.high_water_mark,
            "snapshotId": source_snapshot.id,
            "manifestSha256": source_snapshot.manifest_sha256,
        }
    )
    apps: dict[str, Mapping[str, Any]] = {}
    authors: dict[str, Mapping[str, Any]] = {}
    media: dict[str, Mapping[str, Any]] = {}
    screenshots: dict[str, Mapping[str, Any]] = {}

    for app in mirror.apps:
        _validate_document_id(app.id, "Application")
        author_id = app.author_id or _derived_author_id(app.author_name)
        _validate_document_id(author_id, "Author")
        author_document = _source_document(
            {
                "schemaVersion": 1,
                "displayName": app.author_name,
                "normalizedName": app.author_name.casefold(),
                "sourceAuthorId": app.author_id,
            },
            source_snapshot.id,
        )
        previous_author = authors.setdefault(author_id, author_document)
        if previous_author != author_document:
            raise ValueError("One legacy author ID has conflicting names")

        apps[app.id] = _source_document(
            {
                "schemaVersion": 1,
                "name": app.name,
                "version": app.version,
                "description": app.description,
                "platform": app.platform,
                "model": app.model,
                "categories": list(app.categories),
                "releaseYear": app.release_year,
                "authorId": author_id,
                "authorName": app.author_name,
                "sourceAuthorId": app.author_id,
                "publisherUid": "",
                "publisherEmail": app.publisher_email,
                "mediaSlots": {
                    "disks": list(app.disk_media_ids),
                    "cassette": app.cassette_media_id,
                    "command": app.command_media_id,
                    "basic": app.basic_media_id,
                },
                "screenshotIds": list(app.screenshot_ids),
                "status": "PUBLISHED",
                "revision": 1,
                "firstPublishedAtMs": app.first_published_at_ms,
                "updatedAtMs": app.updated_at_ms,
            },
            source_snapshot.id,
        )

    for media_id, value in mirror.media.items():
        _validate_document_id(media_id, "Media")
        slot = slot_by_media_id[media_id]
        media[media_id] = _source_document(
            {
                "schemaVersion": 1,
                "appId": value.app_id,
                "mediaType": value.media_type,
                "slot": slot,
                "filename": value.filename,
                "description": value.description,
                "contentType": "application/octet-stream",
                "objectPath": value.object.path,
                "size": value.object.size,
                "sha256": value.object.sha256,
                "uploadTimeMs": value.upload_time_ms,
                "publisherUid": "",
            },
            source_snapshot.id,
        )

    for app in mirror.apps:
        for position, screenshot_id in enumerate(app.screenshot_ids):
            value = mirror.screenshots[screenshot_id]
            _validate_document_id(screenshot_id, "Screenshot")
            screenshots[screenshot_id] = _source_document(
                {
                    "schemaVersion": 1,
                    "appId": value.app_id,
                    "filename": value.filename,
                    "contentType": value.content_type,
                    "objectPath": value.object.path,
                    "size": value.object.size,
                    "sha256": value.object.sha256,
                    "uploadTimeMs": value.upload_time_ms,
                    "legacyServingUrl": value.legacy_serving_url,
                    "position": position,
                    "publisherUid": "",
                },
                source_snapshot.id,
            )

    collections = MappingProxyType(
        {
            "apps": MappingProxyType(apps),
            "authors": MappingProxyType(authors),
            "media": MappingProxyType(media),
            "screenshots": MappingProxyType(screenshots),
        }
    )
    manifest_sha256 = _materialization_sha256(source, collections)
    return WorkingCatalogMaterialization(
        id=f"working-{manifest_sha256}",
        source=source,
        collections=collections,
        manifest_sha256=manifest_sha256,
    )


def working_materialization_to_mirror(
    materialization: WorkingCatalogMaterialization,
    object_reader: ObjectReader,
) -> CatalogMirror:
    """Rebuild and independently validate the normalized mirror representation."""

    expected_manifest = _materialization_sha256(
        materialization.source, materialization.collections
    )
    if materialization.manifest_sha256 != expected_manifest:
        raise ValueError("Working catalog materialization manifest is invalid")
    if materialization.id != f"working-{expected_manifest}":
        raise ValueError("Working catalog materialization ID is invalid")

    apps = materialization.collections["apps"]
    authors = materialization.collections["authors"]
    media = materialization.collections["media"]
    screenshots = materialization.collections["screenshots"]
    app_records = []
    media_records = []
    screenshot_records = []

    for app_id, document in sorted(apps.items()):
        _validate_source_document(document, materialization.source["snapshotId"])
        author_id = _required_string(document, "authorId")
        try:
            author = authors[author_id]
        except KeyError as error:
            raise ValueError(f"Working app {app_id} references a missing author") from error
        _validate_source_document(author, materialization.source["snapshotId"])
        if author.get("displayName") != document.get("authorName"):
            raise ValueError(f"Working app {app_id} has inconsistent author metadata")
        if document.get("status") != "PUBLISHED":
            raise ValueError("A source materialization may contain only published apps")
        app_records.append(
            {
                "id": app_id,
                "name": _string(document, "name"),
                "version": _string(document, "version"),
                "description": _string(document, "description"),
                "release_year": _integer(document, "releaseYear"),
                "platform": _required_string(document, "platform"),
                "model": _required_string(document, "model"),
                "categories": _string_list(document, "categories"),
                "author_id": _optional_string(document, "sourceAuthorId"),
                "author_name": _string(document, "authorName"),
                "publisher_email": _string(document, "publisherEmail"),
                "first_published_at_ms": _integer(document, "firstPublishedAtMs"),
                "updated_at_ms": _integer(document, "updatedAtMs"),
                "media_slots": _media_slots_document(document),
                "screenshot_ids": _string_list(document, "screenshotIds"),
            }
        )

    for media_id, document in sorted(media.items()):
        _validate_source_document(document, materialization.source["snapshotId"])
        if document.get("contentType") != "application/octet-stream":
            raise ValueError("Working media content type is invalid")
        slot = _required_string(document, "slot")
        expected_type = _MEDIA_TYPES.get(slot)
        if expected_type is None or document.get("mediaType") != expected_type:
            raise ValueError("Working media type does not match its slot")
        media_records.append(
            {
                "id": media_id,
                "app_id": _required_string(document, "appId"),
                "media_type": expected_type,
                "filename": _string(document, "filename"),
                "description": _string(document, "description"),
                "upload_time_ms": _integer(document, "uploadTimeMs"),
                **_object_descriptor(document),
            }
        )

    for screenshot_id, document in sorted(screenshots.items()):
        _validate_source_document(document, materialization.source["snapshotId"])
        screenshot_records.append(
            {
                "id": screenshot_id,
                "app_id": _required_string(document, "appId"),
                "filename": _string(document, "filename"),
                "content_type": _string(document, "contentType"),
                "upload_time_ms": _integer(document, "uploadTimeMs"),
                "legacy_serving_url": _optional_string(document, "legacyServingUrl"),
                **_object_descriptor(document),
            }
        )

    source = materialization.source
    return CatalogMirror.from_dict(
        {
            "schema_version": 1,
            "source": {
                "project_id": source["projectId"],
                "exported_at": source["exportedAt"],
                "high_water_mark": source["highWaterMark"],
            },
            "apps": app_records,
            "media": media_records,
            "screenshots": screenshot_records,
        },
        object_reader,
    )


def build_working_catalog_candidate(
    baseline: WorkingCatalogMaterialization,
    staged: Mapping[str, Mapping[str, Mapping[str, Any]]],
    object_reader: ObjectReader,
) -> CatalogMirror:
    """Merge isolated new apps into the immutable baseline without activating it."""

    baseline_mirror = working_materialization_to_mirror(baseline, object_reader)
    if set(staged) != set(_COLLECTIONS):
        raise ValueError("Staged working catalog collections are invalid")
    staged_apps = staged["apps"]
    if not staged_apps:
        if any(staged[name] for name in ("authors", "media", "screenshots")):
            raise ValueError("Staged working catalog contains orphan documents")
        return baseline_mirror

    manifest = baseline_mirror.to_dict()
    baseline_apps = {value["id"]: value for value in manifest["apps"]}
    baseline_media = {value["id"]: value for value in manifest["media"]}
    baseline_screenshots = {
        value["id"]: value for value in manifest["screenshots"]
    }
    baseline_app_ids = set(baseline_apps)
    baseline_media_ids = set(baseline_media)
    baseline_screenshot_ids = set(baseline_screenshots)
    app_records: list[dict[str, Any]] = []
    media_records: list[dict[str, Any]] = []
    screenshot_records: list[dict[str, Any]] = []
    referenced_staged_authors: set[str] = set()
    referenced_media: set[str] = set()
    referenced_screenshots: set[str] = set()
    latest_update_ms = 0
    replaced_app_ids: set[str] = set()

    for app_id, document in sorted(staged_apps.items()):
        _validate_document_id(app_id, "Staged application")
        _validate_staged_document(document, "app")
        status = document.get("status")
        if status not in {"STAGING", "DRAFT"}:
            raise ValueError(
                "Publication candidates may include only staged apps or drafts"
            )
        is_draft = status == "DRAFT"
        if is_draft:
            if app_id not in baseline_app_ids:
                raise ValueError("Published app draft has no baseline record")
            source_document = baseline.collections["apps"][app_id]
            if (
                document.get("baseSnapshotId")
                != baseline.source["snapshotId"]
                or document.get("baseSourceFingerprint")
                != source_document.get("sourceFingerprint")
            ):
                raise ValueError("Published app draft is based on another snapshot")
            replaced_app_ids.add(app_id)
        elif app_id in baseline_app_ids:
            raise ValueError("A new staged app collides with a published app ID")
        if document.get("platform") != "TRS80":
            raise ValueError("Staged app platform is invalid")
        author_id = _required_string(document, "authorId")
        author_name = _required_string(document, "authorName")
        author = staged["authors"].get(author_id)
        if author is not None:
            referenced_staged_authors.add(author_id)
            _validate_staged_document(author, "author")
        else:
            author = baseline.collections["authors"].get(author_id)
            if author is None and is_draft and author_id.startswith("draft-"):
                author = {"displayName": author_name}
            elif author is None:
                raise ValueError(f"Staged app {app_id} references a missing author")
            else:
                _validate_source_document(author, baseline.source["snapshotId"])
        if author.get("displayName") != author_name:
            raise ValueError(f"Staged app {app_id} has inconsistent author metadata")
        publisher_uid = _required_string(document, "publisherUid")
        if not publisher_uid:
            raise ValueError("Staged app publisher ownership is missing")
        created_at_ms = _timestamp_ms(document.get("createdAt"), "createdAt")
        updated_at_ms = _timestamp_ms(document.get("updatedAt"), "updatedAt")
        if updated_at_ms < created_at_ms:
            raise ValueError("Staged app update time predates its creation")
        latest_update_ms = max(latest_update_ms, updated_at_ms)
        slots = _media_slots_document(document)
        media_ids = _working_media_ids(slots)
        screenshot_ids = _string_list(document, "screenshotIds")
        if len(screenshot_ids) != len(set(screenshot_ids)):
            raise ValueError("Staged app screenshot IDs must be unique")
        referenced_media.update(media_ids)
        referenced_screenshots.update(screenshot_ids)
        if not is_draft and any(media_id in baseline_media for media_id in media_ids):
            raise ValueError("A new staged app references published media")
        if not is_draft and any(
            screenshot_id in baseline_screenshots for screenshot_id in screenshot_ids
        ):
            raise ValueError("A new staged app references published screenshots")
        if is_draft:
            if any(
                baseline_media[media_id]["app_id"] != app_id
                for media_id in media_ids
                if media_id in baseline_media
            ):
                raise ValueError("Published app draft references another app's media")
            if any(
                baseline_screenshots[screenshot_id]["app_id"] != app_id
                for screenshot_id in screenshot_ids
                if screenshot_id in baseline_screenshots
            ):
                raise ValueError(
                    "Published app draft references another app's screenshot"
                )
        source_author_id = (
            _optional_string(document, "sourceAuthorId") if is_draft else author_id
        )
        app_records.append(
            {
                "id": app_id,
                "name": _string(document, "name"),
                "version": _string(document, "version"),
                "description": _string(document, "description"),
                "release_year": _integer(document, "releaseYear"),
                "platform": "TRS80",
                "model": _required_string(document, "model"),
                "categories": _string_list(document, "categories"),
                "author_id": source_author_id,
                "author_name": author_name,
                "publisher_email": _required_string(document, "publisherEmail"),
                "first_published_at_ms": (
                    _integer(document, "firstPublishedAtMs")
                    if is_draft
                    else created_at_ms
                ),
                "updated_at_ms": updated_at_ms,
                "media_slots": slots,
                "screenshot_ids": screenshot_ids,
            }
        )

    for media_id, document in sorted(staged["media"].items()):
        _validate_document_id(media_id, "Staged media")
        if media_id in baseline_media_ids:
            raise ValueError("Staged media collides with a published media ID")
        _validate_staged_document(document, "media")
        app_id = _required_string(document, "appId")
        if app_id not in staged_apps:
            raise ValueError("Staged media belongs to a non-staged app")
        slot = _required_string(document, "slot")
        media_type = _MEDIA_TYPES.get(slot)
        if media_type is None or document.get("mediaType") != media_type:
            raise ValueError("Staged media type does not match its slot")
        if document.get("contentType") != "application/octet-stream":
            raise ValueError("Staged media content type is invalid")
        media_records.append(
            {
                "id": media_id,
                "app_id": app_id,
                "media_type": media_type,
                "filename": _string(document, "filename"),
                "description": _string(document, "description"),
                "upload_time_ms": _timestamp_ms(
                    document.get("createdAt"), "createdAt"
                ),
                **_object_descriptor(document),
            }
        )

    for screenshot_id, document in sorted(staged["screenshots"].items()):
        _validate_document_id(screenshot_id, "Staged screenshot")
        if screenshot_id in baseline_screenshot_ids:
            raise ValueError(
                "Staged screenshot collides with a published screenshot ID"
            )
        _validate_staged_document(document, "screenshot")
        app_id = _required_string(document, "appId")
        if app_id not in staged_apps:
            raise ValueError("Staged screenshot belongs to a non-staged app")
        expected_position = _string_list(
            staged_apps[app_id], "screenshotIds"
        ).index(screenshot_id)
        position = _integer(document, "position")
        if position != expected_position:
            raise ValueError("Staged screenshot position is inconsistent")
        content_type = _required_string(document, "contentType")
        if not content_type.startswith("image/"):
            raise ValueError("Staged screenshot content type is invalid")
        screenshot_records.append(
            {
                "id": screenshot_id,
                "app_id": app_id,
                "filename": _string(document, "filename"),
                "content_type": content_type,
                "upload_time_ms": _timestamp_ms(
                    document.get("createdAt"), "createdAt"
                ),
                "legacy_serving_url": None,
                **_object_descriptor(document),
            }
        )

    if referenced_staged_authors != set(staged["authors"]):
        raise ValueError("Staged working catalog contains orphan authors")
    if referenced_media - baseline_media_ids != set(staged["media"]):
        raise ValueError("Staged working catalog contains orphan or missing media")
    if referenced_screenshots - baseline_screenshot_ids != set(staged["screenshots"]):
        raise ValueError("Staged working catalog contains orphan or missing screenshots")

    change_manifest = {
        "apps": app_records,
        "media": media_records,
        "screenshots": screenshot_records,
    }
    change_digest = _sha256(change_manifest)
    source = manifest["source"]
    combined_apps = [
        value for value in manifest["apps"] if value["id"] not in replaced_app_ids
    ]
    combined_apps.extend(app_records)
    all_referenced_media = {
        media_id
        for app in combined_apps
        for media_id in _working_media_ids(app["media_slots"])
    }
    all_referenced_screenshots = {
        screenshot_id
        for app in combined_apps
        for screenshot_id in app["screenshot_ids"]
    }
    combined_media = [
        value
        for value in [*manifest["media"], *media_records]
        if value["id"] in all_referenced_media
    ]
    combined_screenshots = [
        value
        for value in [*manifest["screenshots"], *screenshot_records]
        if value["id"] in all_referenced_screenshots
    ]
    return CatalogMirror.from_dict(
        {
            "schema_version": 1,
            "source": {
                "project_id": source["project_id"],
                "exported_at": datetime.fromtimestamp(
                    latest_update_ms / 1000, tz=UTC
                ).isoformat().replace("+00:00", "Z"),
                "high_water_mark": f"working:{change_digest}",
            },
            "apps": combined_apps,
            "media": combined_media,
            "screenshots": combined_screenshots,
            "reconciliation": None,
        },
        object_reader,
    )


def _media_slots(mirror: CatalogMirror) -> dict[str, str]:
    result: dict[str, str] = {}
    for app in mirror.apps:
        values = (
            *(f"disk-{position + 1}" for position in range(4)),
            "cassette",
            "command",
            "basic",
        )
        ids = (
            *app.disk_media_ids,
            app.cassette_media_id,
            app.command_media_id,
            app.basic_media_id,
        )
        for slot, media_id in zip(values, ids, strict=True):
            if media_id is None:
                continue
            previous = result.setdefault(media_id, slot)
            if previous != slot:
                raise ValueError("Published media is referenced from multiple slots")
    return result


def _source_document(value: Mapping[str, Any], snapshot_id: str) -> Mapping[str, Any]:
    stable = _plain(value)
    return MappingProxyType(
        {
            **stable,
            "sourceKind": "APP_ENGINE_MIRROR",
            "sourceSnapshotId": snapshot_id,
            "sourceFingerprint": _sha256(stable),
        }
    )


def _materialization_sha256(
    source: Mapping[str, str],
    collections: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> str:
    if set(collections) != set(_COLLECTIONS):
        raise ValueError("Working catalog materialization collections are invalid")
    return _sha256(
        {
            "schemaVersion": 1,
            "source": dict(source),
            "collections": {
                name: {
                    key: dict(value)
                    for key, value in sorted(collections[name].items())
                }
                for name in _COLLECTIONS
            },
        }
    )


def _validate_source_document(value: Mapping[str, Any], snapshot_id: str) -> None:
    if value.get("sourceKind") != "APP_ENGINE_MIRROR":
        raise ValueError("Working source kind is invalid")
    if value.get("sourceSnapshotId") != snapshot_id:
        raise ValueError("Working document belongs to another source snapshot")
    stable = {
        key: item
        for key, item in value.items()
        if key not in {"sourceKind", "sourceSnapshotId", "sourceFingerprint"}
    }
    if value.get("sourceFingerprint") != _sha256(stable):
        raise ValueError("Working source document fingerprint is invalid")


def _media_slots_document(value: Mapping[str, Any]) -> Mapping[str, Any]:
    slots = value.get("mediaSlots")
    if not isinstance(slots, Mapping):
        raise ValueError("Working app media slots are invalid")
    return {
        "disks": slots.get("disks"),
        "cassette": slots.get("cassette"),
        "command": slots.get("command"),
        "basic": slots.get("basic"),
    }


def _working_media_ids(slots: Mapping[str, Any]) -> tuple[str, ...]:
    disks = slots.get("disks")
    if not isinstance(disks, list) or len(disks) != 4:
        raise ValueError("Staged app must contain exactly four disk slots")
    values = (*disks, slots.get("cassette"), slots.get("command"), slots.get("basic"))
    ids = tuple(value for value in values if isinstance(value, str) and value)
    if any(value is not None and (not isinstance(value, str) or not value) for value in values):
        raise ValueError("Staged app media slot IDs are invalid")
    if len(ids) != len(set(ids)):
        raise ValueError("Staged app media IDs must be unique")
    return ids


def _validate_staged_document(value: Mapping[str, Any], label: str) -> None:
    if value.get("schemaVersion") != 1:
        raise ValueError(f"Staged {label} schema version is invalid")
    if value.get("sourceKind") is not None:
        raise ValueError(f"Staged {label} unexpectedly contains source metadata")


def _timestamp_ms(value: object, field: str) -> int:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"Staged field {field} must be a timezone-aware timestamp")
    result = int(value.timestamp() * 1000)
    if result < 0:
        raise ValueError(f"Staged field {field} must not predate the Unix epoch")
    return result


def _object_descriptor(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "object_path": _required_string(value, "objectPath"),
        "size": _integer(value, "size"),
        "sha256": _required_string(value, "sha256"),
    }


def _string(value: Mapping[str, Any], field: str) -> str:
    result = value.get(field)
    if not isinstance(result, str):
        raise ValueError(f"Working field {field} must be a string")
    return result


def _required_string(value: Mapping[str, Any], field: str) -> str:
    result = _string(value, field)
    if not result:
        raise ValueError(f"Working field {field} must not be empty")
    return result


def _optional_string(value: Mapping[str, Any], field: str) -> str | None:
    result = value.get(field)
    if result is not None and not isinstance(result, str):
        raise ValueError(f"Working field {field} must be a string or null")
    return result


def _integer(value: Mapping[str, Any], field: str) -> int:
    result = value.get(field)
    if isinstance(result, bool) or not isinstance(result, int) or result < 0:
        raise ValueError(f"Working field {field} must be a non-negative integer")
    return result


def _string_list(value: Mapping[str, Any], field: str) -> list[str]:
    result = value.get(field)
    if not isinstance(result, list) or any(not isinstance(item, str) for item in result):
        raise ValueError(f"Working field {field} must be a string list")
    return result


def _derived_author_id(name: str) -> str:
    return f"legacy-unknown-{hashlib.sha256(name.casefold().encode()).hexdigest()[:32]}"


def _validate_document_id(value: str, label: str) -> None:
    if (
        not value
        or value in {".", ".."}
        or "/" in value
        or len(value.encode()) > 1_500
        or (value.startswith("__") and value.endswith("__"))
    ):
        raise ValueError(f"{label} ID is not a safe Firestore document ID")


def _sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _plain(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(dict(value), ensure_ascii=False, separators=(",", ":")))

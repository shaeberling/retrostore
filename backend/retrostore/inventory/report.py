"""Build a sanitized, deterministic report from legacy Datastore entities."""

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from google.cloud.datastore.helpers import GeoPoint
from google.cloud.datastore.key import Key

APPLICATION_KINDS = (
    "AppStoreItem",
    "Author",
    "MediaImage",
    "RetroCardFirmware",
    "RetroStoreUser",
    "SystemState",
    "TrsIoFirmware",
)
INVENTORY_KINDS = (*APPLICATION_KINDS, "__BlobInfo__")
SENSITIVE_KINDS = frozenset({"RetroStoreUser"})
STATE_MAX_AGE = timedelta(days=7)


@dataclass(frozen=True, slots=True)
class SourceEntity:
    kind: str
    key: Any
    properties: Mapping[str, Any]


class EntitySource(Protocol):
    def fetch_kind(self, kind: str) -> Iterable[SourceEntity]: ...


@dataclass(slots=True)
class _BinaryStats:
    count: int = 0
    total_bytes: int = 0
    largest_bytes: int = 0
    digest: Any = None

    def __post_init__(self) -> None:
        self.digest = hashlib.sha256()

    def add(self, entity_key: bytes, value: bytes) -> None:
        self.count += 1
        self.total_bytes += len(value)
        self.largest_bytes = max(self.largest_bytes, len(value))
        _digest_part(self.digest, entity_key)
        _digest_part(self.digest, value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "value_count": self.count,
            "total_bytes": self.total_bytes,
            "largest_bytes": self.largest_bytes,
            "aggregate_sha256": self.digest.hexdigest(),
        }


def build_inventory_report(
    source: EntitySource,
    *,
    project: str,
    database: str = "(default)",
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    now = generated_at or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")
    now = now.astimezone(UTC)

    entities_by_kind = {
        kind: sorted(source.fetch_kind(kind), key=lambda entity: _canonical_bytes(entity.key))
        for kind in INVENTORY_KINDS
    }

    kind_reports = {
        kind: _build_kind_report(kind, entities) for kind, entities in entities_by_kind.items()
    }
    relationships = _reconcile_relationships(entities_by_kind)
    states = _summarize_states(entities_by_kind["SystemState"], now)
    blobstore = _summarize_blobstore(entities_by_kind["__BlobInfo__"])
    search = _summarize_expected_search_index(entities_by_kind["AppStoreItem"])
    findings = _build_findings(relationships, states)

    return {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "source": {"project": project, "database": database},
        "safety": {
            "access_mode": "read-only",
            "contains_entity_keys": False,
            "contains_entity_values": False,
            "contains_binary_data": False,
            "digests_are_aggregate": True,
        },
        "totals": {
            "application_entities": sum(len(entities_by_kind[kind]) for kind in APPLICATION_KINDS),
            "records_scanned": sum(len(entities) for entities in entities_by_kind.values()),
        },
        "kinds": kind_reports,
        "relationships": relationships,
        "system_states": states,
        "blobstore": blobstore,
        "expected_search_index": search,
        "findings": findings,
    }


def _build_kind_report(kind: str, entities: list[SourceEntity]) -> dict[str, Any]:
    type_counts: dict[str, Counter[str]] = defaultdict(Counter)
    binary_stats: dict[str, _BinaryStats] = defaultdict(_BinaryStats)
    digest = hashlib.sha256()

    for entity in entities:
        key_bytes = _canonical_bytes(entity.key)
        if kind not in SENSITIVE_KINDS:
            _digest_part(
                digest,
                _canonical_bytes({"key": entity.key, "properties": entity.properties}),
            )
        _scan_value(
            entity.properties,
            path="",
            entity_key=key_bytes,
            type_counts=type_counts,
            binary_stats=binary_stats,
        )

    return {
        "count": len(entities),
        "aggregate_sha256": None if kind in SENSITIVE_KINDS else digest.hexdigest(),
        "property_shapes": {
            path: {
                "occurrences": sum(counts.values()),
                "types": dict(sorted(counts.items())),
            }
            for path, counts in sorted(type_counts.items())
            if path
        },
        "binary_properties": {
            path: stats.to_dict() for path, stats in sorted(binary_stats.items())
        },
    }


def _scan_value(
    value: Any,
    *,
    path: str,
    entity_key: bytes,
    type_counts: dict[str, Counter[str]],
    binary_stats: dict[str, _BinaryStats],
) -> None:
    if path:
        type_counts[path][_value_type(value)] += 1

    if isinstance(value, Mapping):
        for key in sorted(value, key=str):
            child_path = f"{path}.{key}" if path else str(key)
            _scan_value(
                value[key],
                path=child_path,
                entity_key=entity_key,
                type_counts=type_counts,
                binary_stats=binary_stats,
            )
    elif _is_sequence(value):
        child_path = f"{path}[]"
        for item in value:
            _scan_value(
                item,
                path=child_path,
                entity_key=entity_key,
                type_counts=type_counts,
                binary_stats=binary_stats,
            )
    elif isinstance(value, bytes):
        binary_stats[path].add(entity_key, value)


def _reconcile_relationships(
    entities_by_kind: Mapping[str, list[SourceEntity]],
) -> dict[str, Any]:
    apps = entities_by_kind["AppStoreItem"]
    authors = {_key_value(entity.key) for entity in entities_by_kind["Author"]}
    users = {_key_value(entity.key) for entity in entities_by_kind["RetroStoreUser"]}
    media_by_id = {_key_value(entity.key): entity for entity in entities_by_kind["MediaImage"]}
    blobs = {_key_value(entity.key) for entity in entities_by_kind["__BlobInfo__"]}
    app_ids = {_key_value(entity.key) for entity in apps}

    author_references: list[Any] = []
    publisher_references: list[Any] = []
    media_references: list[tuple[Any, Any]] = []
    screenshot_references: list[Any] = []

    for app in apps:
        app_id = _key_value(app.key)
        listing = _mapping(app.properties.get("listing"))
        author_id = listing.get("authorId")
        if isinstance(author_id, int) and author_id > 0:
            author_references.append(author_id)
        publisher = listing.get("publisherEmail")
        if isinstance(publisher, str) and publisher:
            publisher_references.append(publisher)

        extension = _mapping(app.properties.get("trs80Extension"))
        disk_values = extension.get("disk")
        if _is_sequence(disk_values):
            for media_id in disk_values:
                if isinstance(media_id, int) and media_id > 0:
                    media_references.append((app_id, media_id))
        for field in ("cassette", "command", "basic"):
            media_id = extension.get(field)
            if isinstance(media_id, int) and media_id > 0:
                media_references.append((app_id, media_id))

        screenshots = app.properties.get("screenshotsBlobKeys")
        if _is_sequence(screenshots):
            screenshot_references.extend(
                value for value in screenshots if isinstance(value, str) and value
            )

    referenced_media = {media_id for _, media_id in media_references}
    referenced_blobs = set(screenshot_references)
    missing_media = referenced_media - media_by_id.keys()
    missing_blobs = referenced_blobs - blobs

    ownership_mismatches = 0
    for app_id, media_id in media_references:
        media = media_by_id.get(media_id)
        if media is not None and media.properties.get("appId") != app_id:
            ownership_mismatches += 1

    media_with_missing_parent = sum(
        1 for media in media_by_id.values() if media.properties.get("appId") not in app_ids
    )

    return {
        "authors": {
            "reference_count": len(author_references),
            "unique_reference_count": len(set(author_references)),
            "missing_unique_reference_count": len(set(author_references) - authors),
            "unreferenced_entity_count": len(authors - set(author_references)),
        },
        "publishers": {
            "reference_count": len(publisher_references),
            "unique_reference_count": len(set(publisher_references)),
            "missing_unique_user_count": len(set(publisher_references) - users),
        },
        "media": {
            "reference_count": len(media_references),
            "unique_reference_count": len(referenced_media),
            "missing_unique_reference_count": len(missing_media),
            "unreferenced_entity_count": len(media_by_id.keys() - referenced_media),
            "ownership_mismatch_count": ownership_mismatches,
            "entity_with_missing_parent_count": media_with_missing_parent,
        },
        "screenshots": {
            "reference_count": len(screenshot_references),
            "unique_reference_count": len(referenced_blobs),
            "missing_unique_blob_count": len(missing_blobs),
            "unreferenced_blob_count": len(blobs - referenced_blobs),
        },
    }


def _summarize_states(entities: list[SourceEntity], now: datetime) -> dict[str, Any]:
    max_age_ms = int(STATE_MAX_AGE.total_seconds() * 1000)
    now_ms = int(now.timestamp() * 1000)
    active = 0
    expired = 0
    invalid_timestamp = 0
    invalid_token = 0

    for entity in entities:
        token = _key_value(entity.key)
        if not isinstance(token, int) or not 100 <= token <= 999:
            invalid_token += 1

        timestamp = entity.properties.get("addTimestamp")
        if not isinstance(timestamp, int):
            invalid_timestamp += 1
        elif now_ms - timestamp <= max_age_ms:
            active += 1
        else:
            expired += 1

    return {
        "retention_days": STATE_MAX_AGE.days,
        "active_count": active,
        "expired_count": expired,
        "invalid_timestamp_count": invalid_timestamp,
        "invalid_token_count": invalid_token,
    }


def _summarize_blobstore(entities: list[SourceEntity]) -> dict[str, Any]:
    sizes = [
        value
        for entity in entities
        if isinstance((value := entity.properties.get("size")), int) and value >= 0
    ]
    return {
        "metadata_only": True,
        "content_verified": False,
        "object_count": len(entities),
        "objects_with_size_count": len(sizes),
        "total_bytes": sum(sizes),
        "largest_bytes": max(sizes, default=0),
        "objects_with_md5_count": sum(
            1
            for entity in entities
            if isinstance(entity.properties.get("md5_hash"), str)
            and bool(entity.properties["md5_hash"])
        ),
    }


def _summarize_expected_search_index(apps: list[SourceEntity]) -> dict[str, Any]:
    digest = hashlib.sha256()
    for app in apps:
        listing = _mapping(app.properties.get("listing"))
        document = {
            "id": _key_value(app.key),
            "name": listing.get("name"),
            "description": listing.get("description"),
        }
        _digest_part(digest, _canonical_bytes(document))
    return {
        "name": "AppStoreItem",
        "expected_document_count": len(apps),
        "source_aggregate_sha256": digest.hexdigest(),
        "live_document_count": None,
        "live_index_verified": False,
    }


def _build_findings(
    relationships: Mapping[str, Mapping[str, int]], states: Mapping[str, int]
) -> dict[str, Any]:
    candidates = (
        ("missing_author", "error", relationships["authors"]["missing_unique_reference_count"]),
        (
            "missing_publisher_user",
            "warning",
            relationships["publishers"]["missing_unique_user_count"],
        ),
        ("missing_media", "error", relationships["media"]["missing_unique_reference_count"]),
        ("orphaned_media", "warning", relationships["media"]["unreferenced_entity_count"]),
        ("media_owner_mismatch", "error", relationships["media"]["ownership_mismatch_count"]),
        (
            "media_missing_parent",
            "error",
            relationships["media"]["entity_with_missing_parent_count"],
        ),
        (
            "missing_screenshot_blob",
            "error",
            relationships["screenshots"]["missing_unique_blob_count"],
        ),
        ("orphaned_blob", "warning", relationships["screenshots"]["unreferenced_blob_count"]),
        ("invalid_state_timestamp", "error", states["invalid_timestamp_count"]),
        ("invalid_state_token", "error", states["invalid_token_count"]),
    )
    items = [
        {"code": code, "severity": severity, "affected_count": count}
        for code, severity, count in candidates
        if count
    ]
    return {
        "category_count": len(items),
        "error_category_count": sum(item["severity"] == "error" for item in items),
        "warning_category_count": sum(item["severity"] == "warning" for item in items),
        "items": items,
    }


def _canonical_bytes(value: Any) -> bytes:
    normalized = _canonical_value(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _canonical_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return {"@type": "double", "hex": value.hex()}
    if isinstance(value, bytes):
        return {"@type": "blob", "sha256": hashlib.sha256(value).hexdigest(), "size": len(value)}
    if isinstance(value, datetime):
        normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return {"@type": "timestamp", "value": normalized.astimezone(UTC).isoformat()}
    if isinstance(value, Key):
        return {
            "@type": "key",
            "project": value.project,
            "namespace": value.namespace,
            "database": value.database,
            "flat_path": [_canonical_value(part) for part in value.flat_path],
        }
    if isinstance(value, GeoPoint):
        return {"@type": "geopoint", "latitude": value.latitude, "longitude": value.longitude}
    if isinstance(value, Mapping):
        return {
            "@type": "map",
            "value": [[str(key), _canonical_value(value[key])] for key in sorted(value, key=str)],
        }
    if _is_sequence(value):
        return {"@type": "array", "value": [_canonical_value(item) for item in value]}
    raise TypeError(f"Unsupported Datastore value type: {type(value).__name__}")


def _value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "double"
    if isinstance(value, str):
        return "string"
    if isinstance(value, bytes):
        return "blob"
    if isinstance(value, datetime):
        return "timestamp"
    if isinstance(value, Key):
        return "key"
    if isinstance(value, GeoPoint):
        return "geopoint"
    if isinstance(value, Mapping):
        return "embedded"
    if _is_sequence(value):
        return "array"
    return type(value).__name__


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _key_value(key: Any) -> Any:
    return key.id_or_name if isinstance(key, Key) else key


def _digest_part(digest: Any, value: bytes) -> None:
    digest.update(len(value).to_bytes(8, byteorder="big"))
    digest.update(value)

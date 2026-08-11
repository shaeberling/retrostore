"""Privacy-bounded evidence for comparing normalized catalog snapshots."""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from retrostore.migration.catalog_mirror.catalog import CatalogMirror
from retrostore.migration.catalog_mirror.persistence import build_catalog_snapshot


@dataclass(frozen=True, slots=True)
class CollectionChanges:
    added: tuple[str, ...]
    changed: tuple[str, ...]
    removed: tuple[str, ...]


def catalog_changes(
    baseline: CatalogMirror, candidate: CatalogMirror
) -> dict[str, CollectionChanges]:
    """Return deterministic ID-only changes without exposing catalog field values."""

    if baseline.source_project_id != candidate.source_project_id:
        raise ValueError("Catalog source projects do not match")
    baseline_manifest = baseline.to_dict()
    candidate_manifest = candidate.to_dict()
    return {
        name: _collection_changes(baseline_manifest[name], candidate_manifest[name])
        for name in ("apps", "media", "screenshots")
    }


def changes_dict(value: Mapping[str, CollectionChanges]) -> dict[str, dict[str, Any]]:
    return {
        name: {
            "added_count": len(changes.added),
            "changed_count": len(changes.changed),
            "removed_count": len(changes.removed),
            "added_ids": list(changes.added),
            "changed_ids": list(changes.changed),
            "removed_ids": list(changes.removed),
        }
        for name, changes in value.items()
    }


def snapshot_evidence(mirror: CatalogMirror) -> dict[str, Any]:
    snapshot = build_catalog_snapshot(mirror)
    reconciliation = snapshot.metadata["reconciliation"]
    return {
        "snapshot_id": snapshot.id,
        "manifest_sha256": snapshot.manifest_sha256,
        "source_project_id": mirror.source_project_id,
        "exported_at": mirror.exported_at,
        "high_water_mark": mirror.high_water_mark,
        "counts": {
            "apps": reconciliation["app_count"],
            "media": reconciliation["media_count"],
            "screenshots": reconciliation["screenshot_count"],
            "objects": reconciliation["object_count"],
            "object_bytes": reconciliation["total_bytes"],
        },
        "content_aggregate_sha256": reconciliation["content_aggregate_sha256"],
    }


def _collection_changes(baseline: object, candidate: object) -> CollectionChanges:
    baseline_records = _records_by_id(baseline)
    candidate_records = _records_by_id(candidate)
    baseline_ids = set(baseline_records)
    candidate_ids = set(candidate_records)
    common_ids = baseline_ids & candidate_ids
    return CollectionChanges(
        added=tuple(sorted(candidate_ids - baseline_ids)),
        changed=tuple(
            sorted(
                record_id
                for record_id in common_ids
                if _record_digest(baseline_records[record_id])
                != _record_digest(candidate_records[record_id])
            )
        ),
        removed=tuple(sorted(baseline_ids - candidate_ids)),
    )


def _records_by_id(value: object) -> dict[str, Mapping[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("Catalog collection must be a list")
    result: dict[str, Mapping[str, Any]] = {}
    for record in value:
        if not isinstance(record, Mapping) or not isinstance(record.get("id"), str):
            raise ValueError("Catalog record must contain a string ID")
        record_id = record["id"]
        if record_id in result:
            raise ValueError("Catalog record IDs must be unique")
        result[record_id] = record
    return result


def _record_digest(value: Mapping[str, Any]) -> str:
    body = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(body).hexdigest()

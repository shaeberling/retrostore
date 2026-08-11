"""Build a read-only, deterministic plan for reversing catalog changes to App Engine."""

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from retrostore.migration.catalog_mirror.catalog import CatalogMirror, load_catalog_mirror_archive
from retrostore.migration.catalog_mirror.reconciliation import (
    CollectionChanges,
    catalog_changes,
    changes_dict,
    snapshot_evidence,
)

_MAX_LEGACY_LONG_ID = 2**63 - 1


def build_legacy_reverse_plan(
    baseline: CatalogMirror,
    candidate: CatalogMirror,
    *,
    baseline_archive_sha256: str,
    candidate_archive_sha256: str,
) -> dict[str, Any]:
    """Describe exact reverse operations and unresolved legacy allocations."""

    changes = catalog_changes(baseline, candidate)
    app_upserts = _upsert_ids(changes["apps"])
    media_upserts = _upsert_ids(changes["media"])
    screenshot_writes = _upsert_ids(changes["screenshots"])
    baseline_author_ids = {app.author_id for app in baseline.apps if app.author_id is not None}
    candidate_apps = {app.id: app for app in candidate.apps}
    candidate_added_media_ids = set(changes["media"].added)
    author_ids = {
        candidate_apps[app_id].author_id
        for app_id in app_upserts
        if candidate_apps[app_id].author_id is not None
    }
    author_allocations = sorted(value for value in author_ids if not _is_legacy_long_id(value))
    author_absence_checks = sorted(
        value
        for value in author_ids
        if _is_legacy_long_id(value) and value not in baseline_author_ids
    )
    media_allocations = sorted(
        media_id for media_id in candidate_added_media_ids if not _is_legacy_long_id(media_id)
    )
    media_absence_checks = sorted(
        media_id for media_id in candidate_added_media_ids if _is_legacy_long_id(media_id)
    )
    removal_count = sum(len(value.removed) for value in changes.values())
    baseline_evidence = snapshot_evidence(baseline)
    candidate_evidence = snapshot_evidence(candidate)

    plan: dict[str, Any] = {
        "schema_version": 1,
        "operation": "plan_legacy_catalog_reverse_sync",
        "read_only": True,
        "apply_available": False,
        "privacy": {
            "contains_catalog_field_values": False,
            "contains_binary_objects": False,
            "contains_publisher_identities": False,
            "record_ids_are_included": True,
        },
        "inputs": {
            "baseline_archive_sha256": baseline_archive_sha256,
            "candidate_archive_sha256": candidate_archive_sha256,
            "baseline": baseline_evidence,
            "candidate": candidate_evidence,
        },
        "preconditions": {
            "freeze_replacement_catalog_writes": True,
            "keep_legacy_catalog_writes_disabled_during_apply": True,
            "legacy_catalog_must_exactly_match_baseline_snapshot": baseline_evidence["snapshot_id"],
            "replacement_catalog_must_exactly_match_candidate_snapshot": (
                candidate_evidence["snapshot_id"]
            ),
            "reconcile_before_restoring_one_legacy_writer": True,
        },
        "changes": changes_dict(changes),
        "legacy_operations": {
            "apps": {
                "upsert_ids": list(app_upserts),
                "delete_ids": list(changes["apps"].removed),
            },
            "media": {
                "upsert_ids": list(media_upserts),
                "delete_ids": list(changes["media"].removed),
            },
            "screenshots": {
                "create_or_replace_blob_ids": list(screenshot_writes),
                "detach_ids": list(changes["screenshots"].removed),
                "delete_source_blobs_immediately": False,
            },
            "search": {
                "upsert_document_ids": list(app_upserts),
                "delete_document_ids": list(changes["apps"].removed),
            },
        },
        "legacy_requirements": {
            "author_ids_requiring_allocation": author_allocations,
            "numeric_author_ids_requiring_absence_check": author_absence_checks,
            "media_ids_requiring_allocation": media_allocations,
            "numeric_media_ids_requiring_absence_check": media_absence_checks,
            "screenshot_blob_keys_requiring_creation": list(screenshot_writes),
            "destructive_removal_count": removal_count,
        },
        "ordered_apply_phases": [
            "verify_exact_frozen_baseline_and_candidate",
            "allocate_legacy_numeric_ids_and_upload_screenshot_blobs",
            "upsert_authors_media_and_apps_with_mapped_references",
            "update_search_documents",
            "detach_removed_references_and_delete_obsolete_entities",
            "run_full_legacy_export_and_API_reconciliation",
            "restore_exactly_one_legacy_catalog_writer",
        ],
        "blockers_before_apply_can_exist": [
            "legacy_importer_is_not_enabled",
            *(["legacy_author_id_allocation_map_required"] if author_allocations else []),
            *(["legacy_media_id_allocation_map_required"] if media_allocations else []),
            *(["legacy_screenshot_blob_writer_required"] if screenshot_writes else []),
            *(["explicit_destructive_removal_confirmation_required"] if removal_count else []),
        ],
    }
    plan["plan_sha256"] = _json_sha256(plan)
    return plan


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-archive", type=Path, required=True)
    parser.add_argument("--candidate-archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    baseline = load_catalog_mirror_archive(args.baseline_archive)
    candidate = load_catalog_mirror_archive(args.candidate_archive)
    plan = build_legacy_reverse_plan(
        baseline,
        candidate,
        baseline_archive_sha256=_file_sha256(args.baseline_archive),
        candidate_archive_sha256=_file_sha256(args.candidate_archive),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    print(json.dumps(plan, sort_keys=True, separators=(",", ":")))
    return 0


def _upsert_ids(changes: CollectionChanges) -> tuple[str, ...]:
    return tuple(sorted((*changes.added, *changes.changed)))


def _is_legacy_long_id(value: str) -> bool:
    if not value.isascii() or not value.isdecimal():
        return False
    parsed = int(value)
    return 0 < parsed <= _MAX_LEGACY_LONG_ID and str(parsed) == value


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _json_sha256(value: Any) -> str:
    body = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(body).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())

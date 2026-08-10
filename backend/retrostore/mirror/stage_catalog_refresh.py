"""Stage a refreshed legacy catalog snapshot without moving the active pointer."""

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from retrostore.mirror.catalog import CatalogMirror, load_catalog_mirror_archive
from retrostore.mirror.google_cloud import (
    google_catalog_stores,
    migration_service_account,
    validate_catalog_target,
    validate_migration_identity,
)
from retrostore.mirror.persistence import (
    build_catalog_snapshot,
    load_active_catalog_mirror,
    stage_catalog_mirror,
)


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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--baseline-archive", type=Path)
    parser.add_argument("--project", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--apply-stage", action="store_true")
    parser.add_argument("--confirm-project")
    parser.add_argument("--impersonate-service-account")
    parser.add_argument("--expected-active-snapshot-id")
    parser.add_argument("--expected-active-manifest-sha256")
    args = parser.parse_args(argv)

    validate_catalog_target(
        project=args.project,
        database=args.database,
        bucket=args.bucket,
    )
    candidate = load_catalog_mirror_archive(args.archive)
    if candidate.source_project_id != args.project:
        raise ValueError("Archive source project does not match the target project")
    candidate_snapshot = build_catalog_snapshot(candidate)
    report: dict[str, Any] = {
        "schema_version": 1,
        "operation": "stage_catalog_refresh",
        "applied": False,
        "activation_available": False,
        "target": {
            "project": args.project,
            "database": args.database,
            "bucket": args.bucket,
        },
        "candidate": _snapshot_evidence(candidate),
    }

    if args.baseline_archive is not None:
        baseline = load_catalog_mirror_archive(args.baseline_archive)
        report["baseline"] = _snapshot_evidence(baseline)
        report["changes"] = _changes_dict(catalog_changes(baseline, candidate))

    if args.apply_stage:
        _validate_apply_arguments(args)
        object_store, snapshot_store = google_catalog_stores(
            project=args.project,
            database=args.database,
            bucket=args.bucket,
            impersonate_service_account=args.impersonate_service_account,
        )
        active_before = load_active_catalog_mirror(object_store, snapshot_store)
        active_before_snapshot = build_catalog_snapshot(active_before)
        _require_expected_active(args, active_before_snapshot)
        staged = stage_catalog_mirror(candidate, object_store, snapshot_store)
        active_after = load_active_catalog_mirror(object_store, snapshot_store)
        active_after_snapshot = build_catalog_snapshot(active_after)
        if active_after_snapshot != active_before_snapshot:
            raise RuntimeError("Active catalog pointer changed during stage-only refresh")
        report.update(
            {
                "applied": True,
                "service_account": args.impersonate_service_account,
                "active": _snapshot_evidence(active_before),
                "changes": _changes_dict(catalog_changes(active_before, candidate)),
                "candidate_matches_active": (
                    candidate_snapshot.id == active_before_snapshot.id
                    and candidate_snapshot.manifest_sha256
                    == active_before_snapshot.manifest_sha256
                ),
                "active_pointer_unchanged": True,
                "stage": asdict(staged),
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


def _validate_apply_arguments(args: argparse.Namespace) -> None:
    if args.confirm_project != args.project:
        raise ValueError("--confirm-project must exactly match --project when applying")
    if args.impersonate_service_account is None:
        raise ValueError(
            "--impersonate-service-account is required when applying; expected "
            f"{migration_service_account(args.project)}"
        )
    validate_migration_identity(args.project, args.impersonate_service_account)
    if not args.expected_active_snapshot_id or not args.expected_active_manifest_sha256:
        raise ValueError(
            "Both expected active snapshot arguments are required when applying"
        )


def _require_expected_active(args: argparse.Namespace, active: Any) -> None:
    if (
        args.expected_active_snapshot_id != active.id
        or args.expected_active_manifest_sha256 != active.manifest_sha256
    ):
        raise ValueError("Active catalog snapshot does not match the exact expectation")


def _snapshot_evidence(mirror: CatalogMirror) -> dict[str, Any]:
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


def _collection_changes(
    baseline: object, candidate: object
) -> CollectionChanges:
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
    body = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
    return hashlib.sha256(body).hexdigest()


def _changes_dict(
    value: Mapping[str, CollectionChanges]
) -> dict[str, dict[str, Any]]:
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


if __name__ == "__main__":
    raise SystemExit(main())

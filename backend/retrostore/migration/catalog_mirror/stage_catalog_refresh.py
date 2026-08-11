"""Stage a refreshed legacy catalog snapshot without moving the active pointer."""

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from retrostore.migration.catalog_mirror.catalog import load_catalog_mirror_archive
from retrostore.migration.catalog_mirror.google_cloud import (
    google_catalog_stores,
    migration_service_account,
    validate_catalog_target,
    validate_migration_identity,
)
from retrostore.migration.catalog_mirror.persistence import (
    build_catalog_snapshot,
    load_active_catalog_mirror,
    stage_catalog_mirror,
)
from retrostore.migration.catalog_mirror.reconciliation import (
    catalog_changes,
    changes_dict,
    snapshot_evidence,
)


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
        "candidate": snapshot_evidence(candidate),
    }

    if args.baseline_archive is not None:
        baseline = load_catalog_mirror_archive(args.baseline_archive)
        report["baseline"] = snapshot_evidence(baseline)
        report["changes"] = changes_dict(catalog_changes(baseline, candidate))

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
                "active": snapshot_evidence(active_before),
                "changes": changes_dict(catalog_changes(active_before, candidate)),
                "candidate_matches_active": (
                    candidate_snapshot.id == active_before_snapshot.id
                    and candidate_snapshot.manifest_sha256 == active_before_snapshot.manifest_sha256
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
        raise ValueError("Both expected active snapshot arguments are required when applying")


def _require_expected_active(args: argparse.Namespace, active: Any) -> None:
    if (
        args.expected_active_snapshot_id != active.id
        or args.expected_active_manifest_sha256 != active.manifest_sha256
    ):
        raise ValueError("Active catalog snapshot does not match the exact expectation")


if __name__ == "__main__":
    raise SystemExit(main())

"""Validate and optionally compare-and-swap the active catalog snapshot."""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from retrostore.migration.catalog_mirror.google_cloud import (
    gcloud_impersonated_credentials,
    google_catalog_stores,
    validate_catalog_target,
    validate_migration_identity,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--operation", choices=("activate", "rollback"), required=True)
    parser.add_argument("--candidate-snapshot-id", required=True)
    parser.add_argument("--candidate-manifest-sha256", required=True)
    parser.add_argument("--expected-active-snapshot-id", required=True)
    parser.add_argument("--expected-active-manifest-sha256", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-project")
    parser.add_argument("--confirm-operation")
    parser.add_argument("--confirm-candidate-snapshot-id")
    parser.add_argument("--confirm-expected-active-snapshot-id")
    parser.add_argument("--impersonate-service-account", required=True)
    args = parser.parse_args(argv)

    validate_catalog_target(
        project=args.project,
        database=args.database,
        bucket=args.bucket,
    )
    validate_migration_identity(args.project, args.impersonate_service_account)
    if args.apply:
        confirmations = {
            "--confirm-project": (args.confirm_project, args.project),
            "--confirm-operation": (args.confirm_operation, args.operation),
            "--confirm-candidate-snapshot-id": (
                args.confirm_candidate_snapshot_id,
                args.candidate_snapshot_id,
            ),
            "--confirm-expected-active-snapshot-id": (
                args.confirm_expected_active_snapshot_id,
                args.expected_active_snapshot_id,
            ),
        }
        for flag, (actual, expected) in confirmations.items():
            if actual != expected:
                raise ValueError(f"{flag} must exactly match its target when applying")

    credentials = gcloud_impersonated_credentials(
        project=args.project,
        service_account=args.impersonate_service_account,
    )
    _, snapshot_store = google_catalog_stores(
        project=args.project,
        database=args.database,
        bucket=args.bucket,
        credentials=credentials,
    )
    arguments = {
        "operation": args.operation,
        "candidate_snapshot_id": args.candidate_snapshot_id,
        "candidate_manifest_sha256": args.candidate_manifest_sha256,
        "expected_active_snapshot_id": args.expected_active_snapshot_id,
        "expected_active_manifest_sha256": args.expected_active_manifest_sha256,
    }
    plan = snapshot_store.validate_guarded_activation(**arguments)
    if args.apply:
        snapshot_store.activate_guarded(**arguments, actor=args.actor)

    report: dict[str, Any] = {
        "schema_version": 1,
        "validated": True,
        "applied": args.apply,
        "operation": plan.operation,
        "actor": args.actor,
        "target": {
            "project": args.project,
            "database": args.database,
            "bucket": args.bucket,
        },
        "candidate_snapshot_id": plan.candidate_snapshot_id,
        "candidate_manifest_sha256": plan.candidate_manifest_sha256,
        "expected_active_snapshot_id": plan.expected_active_snapshot_id,
        "expected_active_manifest_sha256": plan.expected_active_manifest_sha256,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

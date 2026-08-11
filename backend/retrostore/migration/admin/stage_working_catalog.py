"""Reconcile the materialized baseline through the stage-only publication boundary."""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from google.cloud import firestore

from retrostore.migration.admin.working_catalog import build_working_catalog_candidate
from retrostore.migration.admin.working_google_cloud import FirestoreWorkingCatalogStore
from retrostore.migration.catalog_mirror import build_catalog_snapshot, load_active_catalog_mirror
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
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-project")
    parser.add_argument("--impersonate-service-account", required=True)
    args = parser.parse_args(argv)

    validate_catalog_target(
        project=args.project,
        database=args.database,
        bucket=args.bucket,
    )
    validate_migration_identity(args.project, args.impersonate_service_account)
    if args.apply and args.confirm_project != args.project:
        raise ValueError("--confirm-project must exactly match --project when applying")

    credentials = gcloud_impersonated_credentials(
        project=args.project,
        service_account=args.impersonate_service_account,
    )
    object_store, snapshot_store = google_catalog_stores(
        project=args.project,
        database=args.database,
        bucket=args.bucket,
        credentials=credentials,
    )
    client = firestore.Client(
        project=args.project,
        database=args.database,
        credentials=credentials,
    )
    working_store = FirestoreWorkingCatalogStore(client)
    materialization = working_store.load_current(actor=args.impersonate_service_account)
    changes = working_store.load_staged_changes()
    candidate_mirror = build_working_catalog_candidate(materialization, changes, object_store)
    candidate = build_catalog_snapshot(candidate_mirror)

    active_mirror = load_active_catalog_mirror(object_store, snapshot_store)
    active = build_catalog_snapshot(active_mirror)
    if (
        active.id != materialization.source["snapshotId"]
        or active.manifest_sha256 != materialization.source["manifestSha256"]
    ):
        raise ValueError("Materialized baseline is not based on the active catalog")
    staged_app_count = len(changes["apps"])
    candidate_matches_active = candidate_mirror.to_dict() == active_mirror.to_dict()
    if staged_app_count == 0 and not candidate_matches_active:
        raise ValueError("Materialized baseline differs from the active catalog")
    if staged_app_count > 0 and candidate_matches_active:
        raise ValueError("Staged changes did not produce a new catalog candidate")
    if args.apply:
        snapshot_store.stage(candidate)

    reconciliation = candidate.metadata["reconciliation"]
    report: dict[str, Any] = {
        "schema_version": 1,
        "applied": args.apply,
        "activation_available": False,
        "target": {
            "project": args.project,
            "database": args.database,
            "bucket": args.bucket,
        },
        "materialization_id": materialization.id,
        "working_manifest_sha256": materialization.manifest_sha256,
        "candidate_snapshot_id": candidate.id,
        "candidate_manifest_sha256": candidate.manifest_sha256,
        "active_snapshot_id": active.id,
        "active_manifest_sha256": active.manifest_sha256,
        "candidate_matches_active": candidate_matches_active,
        "staged_change_counts": {
            name: len(changes[name]) for name in ("apps", "authors", "media", "screenshots")
        },
        "counts": {
            "apps": reconciliation["app_count"],
            "media": reconciliation["media_count"],
            "screenshots": reconciliation["screenshot_count"],
            "objects": reconciliation["object_count"],
        },
        "object_bytes": reconciliation["total_bytes"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Validate and optionally materialize the active catalog into admin collections."""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from google.cloud import firestore

from retrostore.admin.working_catalog import build_working_catalog_materialization
from retrostore.admin.working_google_cloud import FirestoreWorkingCatalogStore
from retrostore.mirror import build_catalog_snapshot, load_active_catalog_mirror
from retrostore.mirror.catalog import load_catalog_mirror_archive
from retrostore.mirror.google_cloud import (
    gcloud_impersonated_credentials,
    google_catalog_stores,
    migration_service_account,
    validate_catalog_target,
    validate_migration_identity,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--project", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-project")
    parser.add_argument("--impersonate-service-account")
    args = parser.parse_args(argv)

    validate_catalog_target(
        project=args.project,
        database=args.database,
        bucket=args.bucket,
    )
    mirror = load_catalog_mirror_archive(args.archive)
    if mirror.source_project_id != args.project:
        raise ValueError("Archive source project does not match the target project")
    source_snapshot = build_catalog_snapshot(mirror)
    materialization = build_working_catalog_materialization(mirror, source_snapshot)
    report: dict[str, Any] = {
        "schema_version": 1,
        "applied": False,
        "target": {
            "project": args.project,
            "database": args.database,
            "bucket": args.bucket,
        },
        "materialization_id": materialization.id,
        "manifest_sha256": materialization.manifest_sha256,
        "source_snapshot_id": source_snapshot.id,
        "source_manifest_sha256": source_snapshot.manifest_sha256,
        "counts": dict(materialization.counts),
    }
    if args.apply:
        if args.confirm_project != args.project:
            raise ValueError("--confirm-project must exactly match --project when applying")
        expected_identity = migration_service_account(args.project)
        if args.impersonate_service_account is None:
            raise ValueError(
                "--impersonate-service-account is required when applying; expected "
                f"{expected_identity}"
            )
        validate_migration_identity(args.project, args.impersonate_service_account)
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
        active = load_active_catalog_mirror(object_store, snapshot_store)
        if active.to_dict() != mirror.to_dict():
            raise ValueError(
                "Archive does not exactly match the active validated catalog snapshot"
            )
        client = firestore.Client(
            project=args.project,
            database=args.database,
            credentials=credentials,
        )
        applied = FirestoreWorkingCatalogStore(client).materialize(
            materialization,
            actor=args.impersonate_service_account,
        )
        report.update(
            {
                "applied": True,
                "materialization_id": applied.materialization_id,
                "manifest_sha256": applied.manifest_sha256,
                "counts": dict(applied.counts),
                "documents_created": applied.documents_created,
                "documents_reused": applied.documents_reused,
                "audit_created": applied.audit_created,
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

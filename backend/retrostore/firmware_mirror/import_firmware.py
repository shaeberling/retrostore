"""Validate and optionally import a firmware archive into isolated cloud resources."""

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from retrostore.firmware_mirror.google_cloud import google_firmware_stores
from retrostore.firmware_mirror.model import load_firmware_mirror_archive
from retrostore.firmware_mirror.persistence import (
    build_firmware_snapshot,
    import_firmware_mirror,
)
from retrostore.mirror.google_cloud import (
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
        project=args.project, database=args.database, bucket=args.bucket
    )
    mirror = load_firmware_mirror_archive(args.archive)
    if mirror.source_project_id != args.project:
        raise ValueError("Archive source project does not match the target project")
    snapshot = build_firmware_snapshot(mirror)
    if args.apply:
        if args.confirm_project != args.project:
            raise ValueError("--confirm-project must exactly match --project when applying")
        if args.impersonate_service_account is None:
            raise ValueError(
                "--impersonate-service-account is required when applying; expected "
                f"{migration_service_account(args.project)}"
            )
        validate_migration_identity(args.project, args.impersonate_service_account)
        object_store, snapshot_store = google_firmware_stores(
            project=args.project,
            database=args.database,
            bucket=args.bucket,
            impersonate_service_account=args.impersonate_service_account,
        )
        report: dict[str, Any] = {
            "schema_version": 1,
            "applied": True,
            "service_account": args.impersonate_service_account,
            "target": _target(args.project, args.database, args.bucket),
            **asdict(import_firmware_mirror(mirror, object_store, snapshot_store)),
        }
    else:
        reconciliation = snapshot.metadata["reconciliation"]
        report = {
            "schema_version": 1,
            "applied": False,
            "target": _target(args.project, args.database, args.bucket),
            "snapshot_id": snapshot.id,
            "manifest_sha256": snapshot.manifest_sha256,
            "firmware_count": reconciliation["firmware_count"],
            "object_count": reconciliation["object_count"],
            "object_bytes": reconciliation["total_bytes"],
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


def _target(project: str, database: str, bucket: str) -> dict[str, str]:
    return {"project": project, "database": database, "bucket": bucket}


if __name__ == "__main__":
    raise SystemExit(main())

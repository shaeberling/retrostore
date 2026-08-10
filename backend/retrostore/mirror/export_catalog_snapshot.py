"""Export one exact isolated cloud catalog snapshot as a normalized archive."""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from retrostore.mirror.catalog import (
    CatalogMirror,
    load_catalog_mirror_archive,
    write_catalog_mirror_archive,
)
from retrostore.mirror.google_cloud import (
    google_catalog_stores,
    validate_catalog_target,
    validate_migration_identity,
)
from retrostore.mirror.persistence import build_catalog_snapshot


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--output-archive", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    parser.add_argument("--impersonate-service-account", required=True)
    args = parser.parse_args(argv)

    validate_catalog_target(
        project=args.project,
        database=args.database,
        bucket=args.bucket,
    )
    validate_migration_identity(args.project, args.impersonate_service_account)
    object_store, snapshot_store = google_catalog_stores(
        project=args.project,
        database=args.database,
        bucket=args.bucket,
        impersonate_service_account=args.impersonate_service_account,
    )
    manifest = snapshot_store.load_snapshot_manifest(
        args.snapshot_id, args.manifest_sha256
    )
    mirror = CatalogMirror.from_dict(manifest, object_store)
    snapshot = build_catalog_snapshot(mirror)
    if snapshot.id != args.snapshot_id or snapshot.manifest_sha256 != args.manifest_sha256:
        raise ValueError("Cloud catalog snapshot does not match the exact requested identity")

    write_catalog_mirror_archive(mirror, args.output_archive)
    reloaded = load_catalog_mirror_archive(args.output_archive)
    if reloaded.to_dict() != mirror.to_dict():
        raise RuntimeError("Exported catalog archive failed round-trip verification")
    reconciliation = snapshot.metadata["reconciliation"]
    report: dict[str, Any] = {
        "schema_version": 1,
        "operation": "export_catalog_snapshot",
        "read_only": True,
        "target": {
            "project": args.project,
            "database": args.database,
            "bucket": args.bucket,
        },
        "snapshot_id": snapshot.id,
        "manifest_sha256": snapshot.manifest_sha256,
        "source_project_id": mirror.source_project_id,
        "source_high_water_mark": mirror.high_water_mark,
        "counts": {
            "apps": reconciliation["app_count"],
            "media": reconciliation["media_count"],
            "screenshots": reconciliation["screenshot_count"],
            "objects": reconciliation["object_count"],
            "object_bytes": reconciliation["total_bytes"],
        },
        "content_aggregate_sha256": reconciliation["content_aggregate_sha256"],
    }
    args.output_report.parent.mkdir(parents=True, exist_ok=True)
    args.output_report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

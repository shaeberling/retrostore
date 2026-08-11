"""Export all live isolated states to a private, checksum-verified archive."""

import argparse
import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from retrostore.api.google_cloud_state import (
    google_state_stores,
    validate_state_identity,
    validate_state_target,
)
from retrostore.migration.state.state_archive import (
    load_state_archive,
    state_archive_evidence,
    write_state_archive,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--output-archive", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    parser.add_argument("--impersonate-service-account", required=True)
    args = parser.parse_args(argv)

    validate_state_target(
        project=args.project,
        database=args.database,
        bucket=args.bucket,
    )
    validate_state_identity(args.project, args.impersonate_service_account)
    payload_store, token_store = google_state_stores(
        project=args.project,
        database=args.database,
        bucket=args.bucket,
        impersonate_service_account=args.impersonate_service_account,
    )
    captured_at = datetime.now(UTC)
    records = token_store.list_live(now=captured_at)
    bodies = tuple((record, payload_store.read(record.payload)) for record in records)
    write_state_archive(
        bodies,
        source_project_id=args.project,
        captured_at=captured_at,
        path=args.output_archive,
    )
    archive = load_state_archive(args.output_archive)
    if archive.source_project_id != args.project or archive.captured_at != captured_at:
        raise RuntimeError("Exported state archive failed source reconciliation")
    evidence = state_archive_evidence(archive)
    report: dict[str, Any] = {
        "schema_version": 1,
        "operation": "export_live_state_snapshot",
        "read_only": True,
        "target": {
            "project": args.project,
            "database": args.database,
            "bucket": args.bucket,
        },
        "captured_at": captured_at.isoformat().replace("+00:00", "Z"),
        "archive_sha256": _file_sha256(args.output_archive),
        "evidence": evidence,
        "safety": {
            "report_contains_state_tokens": False,
            "report_contains_state_payloads": False,
            "archive_contains_state_tokens": True,
            "archive_contains_state_payloads": True,
            "archive_file_mode": "0600",
        },
    }
    args.output_report.parent.mkdir(parents=True, exist_ok=True)
    args.output_report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())

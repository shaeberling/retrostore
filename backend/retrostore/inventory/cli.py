"""Command-line entry point for the sanitized production inventory report."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from retrostore.inventory.datastore_source import create_datastore_source
from retrostore.inventory.report import build_inventory_report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read legacy Datastore and emit a sanitized reconciliation report."
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--database", default="(default)")
    parser.add_argument("--auth", choices=("adc", "gcloud"), default="adc")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--fail-on-integrity-errors",
        action="store_true",
        help="Exit with status 2 if the sanitized report contains error findings.",
    )
    args = parser.parse_args()

    source = create_datastore_source(
        project=args.project,
        database=args.database,
        auth=args.auth,
    )
    report = build_inventory_report(
        source,
        project=args.project,
        database=args.database,
        generated_at=datetime.now(UTC),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    if args.fail_on_integrity_errors and report["findings"]["error_category_count"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()

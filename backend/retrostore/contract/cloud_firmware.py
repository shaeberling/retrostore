"""Compare live firmware routes with an in-process active cloud mirror."""

import argparse
import json
from pathlib import Path

import httpx

from retrostore.api_compat.firmware import MirrorFirmwareStorage
from retrostore.contract.firmware import (
    capture_firmware,
    capture_firmware_with_client,
    compare_firmware_captures,
)
from retrostore.firmware_mirror import load_active_firmware_mirror
from retrostore.firmware_mirror.google_cloud import google_firmware_stores
from retrostore.mirror.google_cloud import (
    gcloud_impersonated_credentials,
    validate_catalog_target,
)
from services.api_compat.app import create_app


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-url", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--impersonate-service-account", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args()

    validate_catalog_target(
        project=args.project, database=args.database, bucket=args.bucket
    )
    expected_identity = f"retrostore-api@{args.project}.iam.gserviceaccount.com"
    if args.impersonate_service_account != expected_identity:
        raise ValueError(
            "Firmware comparison must impersonate the compatibility API identity"
        )
    credentials = gcloud_impersonated_credentials(
        project=args.project,
        service_account=args.impersonate_service_account,
    )
    objects, snapshots = google_firmware_stores(
        project=args.project,
        database=args.database,
        bucket=args.bucket,
        credentials=credentials,
    )
    mirror = load_active_firmware_mirror(objects, snapshots)
    app = create_app(
        {
            "TESTING": True,
            "RETROSTORE_API_HANDLERS": {},
            "RETROSTORE_FIRMWARE_STORAGE": MirrorFirmwareStorage(mirror),
        }
    )
    reference = capture_firmware(args.reference_url, args.timeout_seconds)
    transport = httpx.WSGITransport(app=app)
    candidate_url = "in-process://isolated-firmware-candidate"
    with httpx.Client(
        transport=transport,
        base_url="http://firmware-candidate.test",
        timeout=args.timeout_seconds,
    ) as candidate_client:
        candidate = capture_firmware_with_client(candidate_url, candidate_client)
    report = compare_firmware_captures(reference, candidate)
    report["candidate_identity"] = args.impersonate_service_account
    report["candidate_resources"] = {
        "project": args.project,
        "database": args.database,
        "bucket": args.bucket,
        "high_water_mark": mirror.high_water_mark,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report["summary"], sort_keys=True))
    return 0 if report["summary"]["different"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

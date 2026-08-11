"""Compare App Engine with an in-process candidate backed by real isolated cloud data."""

import argparse
import json
from pathlib import Path

import httpx

from retrostore.api.google_cloud_state import (
    google_state_storage,
    validate_state_identity,
    validate_state_target,
)
from retrostore.contract.approvals import evaluate_approvals
from retrostore.contract.capture import capture_scenarios, capture_scenarios_with_client
from retrostore.contract.compare_hosts import compare_captures
from retrostore.contract.exhaustive import discover_exhaustive_corpus
from retrostore.migration.catalog_mirror import MirrorApiDataStore, load_active_catalog_mirror
from retrostore.migration.catalog_mirror.google_cloud import (
    gcloud_impersonated_credentials,
    google_catalog_stores,
    validate_catalog_target,
)
from services.api.app import create_app


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-url", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--catalog-database", required=True)
    parser.add_argument("--assets-bucket", required=True)
    parser.add_argument("--state-database", required=True)
    parser.add_argument("--state-bucket", required=True)
    parser.add_argument("--impersonate-service-account", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args()

    validate_catalog_target(
        project=args.project,
        database=args.catalog_database,
        bucket=args.assets_bucket,
    )
    validate_state_target(
        project=args.project,
        database=args.state_database,
        bucket=args.state_bucket,
    )
    validate_state_identity(args.project, args.impersonate_service_account)

    credentials = gcloud_impersonated_credentials(
        project=args.project,
        service_account=args.impersonate_service_account,
    )
    object_store, snapshot_store = google_catalog_stores(
        project=args.project,
        database=args.catalog_database,
        bucket=args.assets_bucket,
        credentials=credentials,
    )
    state_storage = google_state_storage(
        project=args.project,
        database=args.state_database,
        bucket=args.state_bucket,
        credentials=credentials,
    )
    mirror = load_active_catalog_mirror(object_store, snapshot_store)
    app = create_app(
        {
            "TESTING": True,
            "RETROSTORE_API_STORAGE": MirrorApiDataStore(
                mirror,
                screenshot_url=lambda screenshot: screenshot.legacy_serving_url or "",
                state_storage=state_storage,
            ),
        }
    )

    with httpx.Client(
        base_url=args.reference_url,
        follow_redirects=False,
        timeout=args.timeout_seconds,
    ) as reference_client:
        corpus = discover_exhaustive_corpus(reference_client)
    reference = capture_scenarios(
        args.reference_url,
        corpus.scenarios,
        args.timeout_seconds,
    )
    transport = httpx.WSGITransport(app=app)
    candidate_url = "in-process://isolated-cloud-candidate"
    with httpx.Client(
        transport=transport,
        base_url="http://cloud-candidate.test",
        timeout=args.timeout_seconds,
    ) as candidate_client:
        candidate = capture_scenarios_with_client(
            candidate_url,
            corpus.scenarios,
            candidate_client,
        )

    report = evaluate_approvals(compare_captures(reference, candidate), ())
    report["scope"] = corpus.scope()
    report["candidate_identity"] = args.impersonate_service_account
    report["candidate_resources"] = {
        "project": args.project,
        "catalog_database": args.catalog_database,
        "assets_bucket": args.assets_bucket,
        "state_database": args.state_database,
        "state_bucket": args.state_bucket,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"scope": report["scope"], "summary": report["summary"]}))
    return 0 if report["approval_gate"]["passes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

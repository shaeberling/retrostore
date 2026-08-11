"""Audit HTTP/HTTPS parity across every current public read surface."""

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from retrostore.contract.approvals import evaluate_approvals
from retrostore.contract.exhaustive import compare_exhaustive
from retrostore.contract.legacy_downloads import (
    compare_download_clients,
    discover_download_scenarios_from_reference,
)
from retrostore.contract.public_redirects import compare_public_redirect_clients
from retrostore.contract.public_site_assets import compare_public_site_bundle

_HTTPS_ORIGIN = "https://retrostore.org"
_HTTP_ORIGIN = "http://retrostore.org"


def assemble_public_transport_report(
    *,
    api: Mapping[str, Any],
    downloads: Mapping[str, Any],
    redirects: Mapping[str, Any],
    static_https: Mapping[str, Any],
    static_http: Mapping[str, Any],
    public_listing_matches: bool,
    public_listing: Mapping[str, Any],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    now = generated_at or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")
    api_differences = [
        {
            "scenario": result["scenario"],
            "fields": sorted(result["differences"]),
        }
        for result in api["results"]
        if result["differences"]
    ]
    static_differences = sorted(
        {
            difference["path"]
            for report in (static_https, static_http)
            for difference in report["differences"]
        }
    )
    surface_results = {
        "api": api["approval_gate"]["passes"] and not api_differences,
        "legacy_downloads": downloads["summary"]["passes"],
        "public_redirects": redirects["summary"]["passes"],
        "public_static_site": not static_differences,
        "legacy_public_listing": public_listing_matches,
    }
    scenario_count = (
        api["summary"]["total"]
        + downloads["summary"]["total"]
        + redirects["summary"]["total"]
        + static_https["summary"]["total"]
        + 1
    )
    different = (
        len(api_differences)
        + downloads["summary"]["different"]
        + redirects["summary"]["different"]
        + len(static_differences)
        + (not public_listing_matches)
    )
    return {
        "schema_version": 1,
        "generated_at": now.astimezone(UTC).isoformat(),
        "kind": "retrostore_public_http_https_transport_parity",
        "reference_url": _HTTPS_ORIGIN,
        "candidate_url": _HTTP_ORIGIN,
        "safety": {
            "read_only": True,
            "contains_request_or_response_payloads": False,
            "contains_catalog_values": False,
            "contains_app_ids_or_filenames": False,
            "contains_credentials": False,
            "production_changed": False,
        },
        "scope": {
            "scenario_count": scenario_count,
            "api_scenario_count": api["summary"]["total"],
            "download_scenario_count": downloads["summary"]["total"],
            "redirect_scenario_count": redirects["summary"]["total"],
            "static_scenario_count": static_https["summary"]["total"],
            "public_listing_scenario_count": 1,
            **{
                key: api["scope"][key]
                for key in (
                    "app_count",
                    "media_object_count",
                    "media_bytes",
                    "media_region_count",
                )
            },
        },
        "summary": {
            "total": scenario_count,
            "matching": scenario_count - different,
            "different": different,
            "passes": all(surface_results.values()),
        },
        "surfaces": {
            "api": {
                "scope": api["scope"],
                "summary": api["summary"],
                "approval_gate": api["approval_gate"],
                "differences": api_differences,
                "passes": surface_results["api"],
            },
            "legacy_downloads": downloads,
            "public_redirects": redirects,
            "public_static_site": {
                "scenario_count": static_https["summary"]["total"],
                "differences": static_differences,
                "https_expected_source_passes": static_https["summary"]["passes"],
                "http_expected_source_passes": static_http["summary"]["passes"],
                "passes": surface_results["public_static_site"],
            },
            "legacy_public_listing": {
                "matches": public_listing_matches,
                **public_listing,
                "passes": surface_results["legacy_public_listing"],
            },
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static-bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args(argv)
    if args.output.exists():
        raise FileExistsError(f"Transport report already exists: {args.output}")

    api = evaluate_approvals(
        compare_exhaustive(
            _HTTPS_ORIGIN,
            _HTTP_ORIGIN,
            timeout_seconds=args.timeout_seconds,
        ),
        (),
    )
    with (
        httpx.Client(
            base_url=_HTTPS_ORIGIN,
            follow_redirects=False,
            timeout=args.timeout_seconds,
            trust_env=False,
        ) as https,
        httpx.Client(
            base_url=_HTTP_ORIGIN,
            follow_redirects=False,
            timeout=args.timeout_seconds,
            trust_env=False,
        ) as http,
    ):
        scenarios = discover_download_scenarios_from_reference(https)
        downloads = compare_download_clients(
            https,
            http,
            scenarios,
            reference_url=_HTTPS_ORIGIN,
            candidate_label=_HTTP_ORIGIN,
        )
        redirects = compare_public_redirect_clients(
            https,
            http,
            reference_url=_HTTPS_ORIGIN,
            candidate_label=_HTTP_ORIGIN,
        )
        static_https = compare_public_site_bundle(
            https,
            args.static_bundle,
            reference_url=_HTTPS_ORIGIN,
        )
        static_http = compare_public_site_bundle(
            http,
            args.static_bundle,
            reference_url=_HTTP_ORIGIN,
        )
        listing_https = _response_fingerprint(https.get("/rpc?m=pubapplist"))
        listing_http = _response_fingerprint(http.get("/rpc?m=pubapplist"))
        listing = {
            "https": listing_https,
            "http": listing_http,
        }
    report = assemble_public_transport_report(
        api=api,
        downloads=downloads,
        redirects=redirects,
        static_https=static_https,
        static_http=static_http,
        public_listing_matches=listing_https == listing_http,
        public_listing=listing,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"scope": report["scope"], "summary": report["summary"]}))
    return 0 if report["summary"]["passes"] else 1


def _response_fingerprint(response: httpx.Response) -> dict[str, Any]:
    return {
        "status": response.status_code,
        "content_type": response.headers.get("content-type"),
        "access_control_allow_origin": response.headers.get("access-control-allow-origin"),
        "body_bytes": len(response.content),
        "body_sha256": hashlib.sha256(response.content).hexdigest(),
    }


if __name__ == "__main__":
    raise SystemExit(main())

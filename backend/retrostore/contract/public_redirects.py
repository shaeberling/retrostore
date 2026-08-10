"""Compare the six exact public website redirects without following them."""

import argparse
import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from retrostore.contract.exhaustive import _gcloud_identity_token
from retrostore.contract.legacy_downloads import (
    _CANDIDATE_IDENTITY,
    _candidate_origin,
)
from services.api_compat.app import LEGACY_PUBLIC_REDIRECTS


def compare_public_redirect_clients(
    reference: httpx.Client,
    candidate: httpx.Client,
    *,
    reference_url: str,
    candidate_label: str,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    now = generated_at or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")

    results = []
    for base_path in LEGACY_PUBLIC_REDIRECTS:
        for path in (base_path, f"{base_path}/"):
            expected = _response_fingerprint(reference.get(path))
            actual = _response_fingerprint(candidate.get(path))
            results.append(
                {
                    "path": path,
                    "matches": expected == actual,
                    "reference": expected,
                    "candidate": actual,
                }
            )
    different = [
        {"path": result["path"]} for result in results if not result["matches"]
    ]
    matching = len(results) - len(different)
    return {
        "schema_version": 1,
        "generated_at": now.astimezone(UTC).isoformat(),
        "kind": "retrostore_public_redirect_comparison",
        "reference_url": reference_url,
        "candidate": candidate_label,
        "safety": {
            "read_only": True,
            "follows_redirects": False,
            "contains_credentials": False,
            "contains_catalog_values": False,
        },
        "scope": {"scenario_count": len(results)},
        "summary": {
            "total": len(results),
            "matching": matching,
            "different": len(different),
            "passes": not different,
        },
        "differences": different,
        "results": results,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-url", required=True)
    parser.add_argument("--candidate-url", required=True)
    parser.add_argument("--candidate-audience")
    parser.add_argument("--candidate-gcloud-identity-token-service-account", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args(argv)

    if args.reference_url.rstrip("/") != "https://retrostore.org":
        raise ValueError("--reference-url must be exactly https://retrostore.org")
    candidate = _candidate_origin(args.candidate_url)
    if args.candidate_gcloud_identity_token_service_account != _CANDIDATE_IDENTITY:
        raise ValueError("The exact private API runtime identity is required")
    audience = args.candidate_audience or candidate
    if _candidate_origin(audience) != audience:
        raise ValueError("Candidate audience must be an approved candidate origin")
    token = _gcloud_identity_token(
        audience,
        args.candidate_gcloud_identity_token_service_account,
    )
    with httpx.Client(
        base_url=args.reference_url,
        follow_redirects=False,
        timeout=args.timeout_seconds,
    ) as reference, httpx.Client(
        base_url=candidate,
        headers={"Authorization": f"Bearer {token}"},
        follow_redirects=False,
        timeout=args.timeout_seconds,
    ) as candidate_client:
        report = compare_public_redirect_clients(
            reference,
            candidate_client,
            reference_url=args.reference_url,
            candidate_label=candidate,
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"scope": report["scope"], "summary": report["summary"]}))
    return 0 if report["summary"]["passes"] else 1


def _response_fingerprint(response: httpx.Response) -> dict[str, object]:
    body = response.content
    return {
        "status": response.status_code,
        "location": response.headers.get("location"),
        "content_type": response.headers.get("content-type", "")
        .partition(";")[0]
        .casefold(),
        "body_bytes": len(body),
        "body_sha256": hashlib.sha256(body).hexdigest(),
    }


if __name__ == "__main__":
    raise SystemExit(main())

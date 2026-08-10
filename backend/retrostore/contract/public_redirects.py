"""Compare the six exact public website redirects without following them."""

import hashlib
from datetime import UTC, datetime
from typing import Any

import httpx

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

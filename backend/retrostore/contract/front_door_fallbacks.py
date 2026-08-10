"""Compare safe paths that must continue to fall through to App Engine."""

import argparse
import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from retrostore.contract.exhaustive import _with_candidate_host_header

FALLBACK_SCENARIOS = (
    ("unknown-root", "/__retrostore_front_door_fallback__"),
    ("missing-css", "/css/__retrostore_front_door_fallback__.css"),
    ("missing-favicon", "/favicon/__retrostore_front_door_fallback__.png"),
    ("missing-gfx", "/gfx/__retrostore_front_door_fallback__.png"),
    ("missing-js", "/js/__retrostore_front_door_fallback__.js"),
    ("missing-lightbox", "/lightbox2/__retrostore_front_door_fallback__.png"),
    ("missing-public", "/public/__retrostore_front_door_fallback__.html"),
    ("missing-vendor", "/vendor/__retrostore_front_door_fallback__.js"),
    ("public-directory", "/public/"),
    ("redirect-near-miss", "/community/__retrostore_front_door_fallback__"),
    ("download-near-miss", "/downloadapp/__retrostore_front_door_fallback__"),
    ("unknown-api-method", "/api/__retrostore_front_door_fallback__"),
)

_MAX_BODY_BYTES = 64 * 1024


def compare_front_door_fallback_clients(
    reference: httpx.Client,
    candidate: httpx.Client,
    *,
    reference_url: str,
    candidate_url: str,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Compare bounded response semantics without retaining response bodies."""
    now = generated_at or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")

    results = []
    for name, path in FALLBACK_SCENARIOS:
        expected = _response_fingerprint(reference.get(path))
        actual = _response_fingerprint(candidate.get(path))
        matches = expected == actual
        results.append(
            {
                "name": name,
                "path": path,
                "matches": matches,
                "reference": expected,
                "candidate": actual,
            }
        )
    differences = [
        {"name": result["name"], "path": result["path"]}
        for result in results
        if not result["matches"]
    ]
    return {
        "schema_version": 1,
        "generated_at": now.astimezone(UTC).isoformat(),
        "kind": "retrostore_front_door_fallback_comparison",
        "reference_url": _origin(reference_url),
        "candidate_url": _origin(candidate_url),
        "safety": {
            "read_only": True,
            "follows_redirects": False,
            "contains_response_bodies": False,
            "contains_credentials": False,
            "contains_catalog_values": False,
            "contains_state_tokens": False,
        },
        "scope": {"scenario_count": len(results)},
        "summary": {
            "total": len(results),
            "matching": len(results) - len(differences),
            "different": len(differences),
            "passes": not differences,
        },
        "differences": differences,
        "results": results,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-url", required=True)
    parser.add_argument("--candidate-url", required=True)
    parser.add_argument("--candidate-host-header")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args(argv)

    reference_url = _origin(args.reference_url)
    candidate_url = _origin(args.candidate_url)
    if reference_url not in {"http://retrostore.org", "https://retrostore.org"}:
        raise ValueError("Reference URL must be the production HTTP or HTTPS origin")
    with httpx.Client(
        base_url=reference_url,
        follow_redirects=False,
        timeout=args.timeout_seconds,
    ) as reference, httpx.Client(
        base_url=candidate_url,
        headers=_with_candidate_host_header(
            candidate_url,
            args.candidate_host_header,
        ),
        follow_redirects=False,
        timeout=args.timeout_seconds,
    ) as candidate:
        report = compare_front_door_fallback_clients(
            reference,
            candidate,
            reference_url=reference_url,
            candidate_url=candidate_url,
        )
        if args.candidate_host_header is not None:
            report["candidate_host_header"] = args.candidate_host_header

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"scope": report["scope"], "summary": report["summary"]}))
    return 0 if report["summary"]["passes"] else 1


def _response_fingerprint(response: httpx.Response) -> dict[str, object]:
    body = response.content
    if len(body) > _MAX_BODY_BYTES:
        raise ValueError("Fallback response exceeds the safe body limit")
    behavior = _behavior(response.status_code, body)
    fingerprint: dict[str, object] = {
        "status": response.status_code,
        "content_type": response.headers.get("content-type", "")
        .partition(";")[0]
        .casefold(),
        "behavior": behavior,
    }
    if behavior != "legacy_login_forward":
        fingerprint.update(
            {
                "body_bytes": len(body),
                "body_sha256": hashlib.sha256(body).hexdigest(),
            }
        )
    return fingerprint


def _behavior(status: int, body: bytes) -> str:
    if status == 200 and b"/_ah/conflogin?continue=" in body:
        return "legacy_login_forward"
    if status == 404 and not body:
        return "empty_404"
    if status == 404:
        return "body_404"
    if 400 <= status < 500:
        return "client_error"
    return "other"


def _origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("URL must be an HTTP(S) origin without credentials or a path")
    return f"{parsed.scheme}://{parsed.netloc}"


if __name__ == "__main__":
    raise SystemExit(main())

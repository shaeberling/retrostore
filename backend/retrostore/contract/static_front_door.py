"""Verify every candidate static route against a checksum-closed local bundle."""

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from retrostore.contract.exhaustive import _with_candidate_host_header
from retrostore.public_site_deployment import plan_public_site_deployment

_PUBLIC_BUCKET = "trs-80-retrostore-public"


@dataclass(frozen=True, slots=True)
class StaticExpectation:
    path: str
    body_bytes: int
    body_sha256: str
    content_type: str


def load_static_expectations(
    bundle: Path,
    build_report: Mapping[str, Any],
) -> tuple[StaticExpectation, ...]:
    """Verify the bundle and return the exact 79 front-door expectations."""
    plan = plan_public_site_deployment(
        bundle,
        build_report,
        target_bucket=_PUBLIC_BUCKET,
    )
    by_object = {item["object"]: item for item in plan["operations"]["uploads"]}
    if "index.html" not in by_object:
        raise ValueError("Static website bundle has no index.html object")
    expectations = [
        _expectation("/", by_object["index.html"]),
        *(
            _expectation(f"/{name}", item)
            for name, item in sorted(by_object.items())
        ),
    ]
    if len(expectations) != 79:
        raise ValueError("Static front-door route count changed")
    return tuple(expectations)


def compare_static_client(
    candidate: httpx.Client,
    expectations: Sequence[StaticExpectation],
    *,
    candidate_label: str,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    now = generated_at or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")

    differences = []
    matching = 0
    response_bytes = 0
    for expectation in expectations:
        response = candidate.get(expectation.path)
        response_bytes += len(response.content)
        fields = _difference_fields(expectation, response)
        if fields:
            differences.append({"path": expectation.path, "fields": fields})
        else:
            matching += 1
    return {
        "schema_version": 1,
        "generated_at": now.astimezone(UTC).isoformat(),
        "kind": "retrostore_static_front_door_comparison",
        "candidate": candidate_label,
        "safety": {
            "read_only": True,
            "contains_response_bodies": False,
            "contains_credentials": False,
            "contains_catalog_values": False,
        },
        "scope": {
            "scenario_count": len(expectations),
            "candidate_response_bytes": response_bytes,
        },
        "summary": {
            "total": len(expectations),
            "matching": matching,
            "different": len(differences),
            "passes": not differences,
        },
        "differences": differences,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--build-report", type=Path, required=True)
    parser.add_argument("--candidate-url", required=True)
    parser.add_argument("--candidate-host-header", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args(argv)

    build_report = json.loads(args.build_report.read_text())
    if not isinstance(build_report, dict):
        raise ValueError("Build report must be a JSON object")
    candidate = args.candidate_url.rstrip("/")
    headers = _with_candidate_host_header(
        candidate,
        args.candidate_host_header,
    )
    expectations = load_static_expectations(args.bundle, build_report)
    with httpx.Client(
        base_url=candidate,
        headers=headers,
        follow_redirects=False,
        timeout=args.timeout_seconds,
    ) as client:
        report = compare_static_client(
            client,
            expectations,
            candidate_label=candidate,
        )
        report["candidate_host_header"] = args.candidate_host_header
    if args.output.exists():
        raise FileExistsError(f"Static comparison output already exists: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"scope": report["scope"], "summary": report["summary"]}))
    return 0 if report["summary"]["passes"] else 1


def _expectation(path: str, item: Mapping[str, Any]) -> StaticExpectation:
    return StaticExpectation(
        path=path,
        body_bytes=int(item["size"]),
        body_sha256=str(item["sha256"]),
        content_type=str(item["content_type"]).casefold(),
    )


def _difference_fields(
    expected: StaticExpectation,
    response: httpx.Response,
) -> list[str]:
    actual = {
        "status": response.status_code,
        "body_bytes": len(response.content),
        "body_sha256": hashlib.sha256(response.content).hexdigest(),
        "content_type": response.headers.get("content-type", "")
        .partition(";")[0]
        .casefold(),
        "cache_control": response.headers.get("cache-control"),
        "access_control_allow_origin": response.headers.get(
            "access-control-allow-origin"
        ),
    }
    wanted = {
        "status": 200,
        "body_bytes": expected.body_bytes,
        "body_sha256": expected.body_sha256,
        "content_type": expected.content_type,
        "cache_control": "no-store",
        "access_control_allow_origin": "*",
    }
    return sorted(field for field in wanted if wanted[field] != actual[field])


if __name__ == "__main__":
    raise SystemExit(main())

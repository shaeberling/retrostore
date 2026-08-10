"""Compare the legacy public website app list with the normalized candidate."""

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from retrostore.contract.exhaustive import (
    _gcloud_identity_token,
    _public_candidate_origin,
    _with_candidate_host_header,
)
from retrostore.contract.legacy_downloads import (
    _CANDIDATE_IDENTITY,
    _candidate_origin,
)
from services.api_compat.app import create_archive_app

_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_MAX_APPS = 1_000
_MAX_SCREENSHOTS = 64
_REQUIRED_FIELDS = frozenset(
    {
        "name",
        "version",
        "author",
        "description",
        "screenshots",
        "reportUrl",
        "downloadUrl",
    }
)
_OPTIONAL_FIELDS = frozenset({"emulatorAppId"})


def compare_public_app_clients(
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

    reference_response = reference.get("/rpc?m=pubapplist")
    candidate_response = candidate.get("/public/apps.json")
    expected = _normalize_response(reference_response)
    actual = _normalize_response(candidate_response)
    differences = _differences(expected, actual)
    return {
        "schema_version": 1,
        "generated_at": now.astimezone(UTC).isoformat(),
        "kind": "retrostore_public_website_app_list_comparison",
        "reference_url": reference_url,
        "candidate": candidate_label,
        "safety": {
            "read_only": True,
            "contains_app_ids": False,
            "contains_app_names": False,
            "contains_descriptions": False,
            "contains_screenshot_urls": False,
            "contains_credentials": False,
        },
        "scope": {
            "reference_app_count": len(expected["apps"]),
            "candidate_app_count": len(actual["apps"]),
            "reference_response_bytes": len(reference_response.content),
            "candidate_response_bytes": len(candidate_response.content),
        },
        "integrity": {
            "reference_aggregate_sha256": _json_sha256(expected["apps"]),
            "candidate_aggregate_sha256": _json_sha256(actual["apps"]),
        },
        "summary": {
            "different": len(differences),
            "passes": not differences,
        },
        "differences": differences,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--reference-url", required=True)
    parser.add_argument("--candidate-url")
    parser.add_argument("--candidate-audience")
    parser.add_argument("--candidate-gcloud-identity-token-service-account")
    parser.add_argument("--candidate-host-header")
    parser.add_argument("--public-candidate", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args(argv)

    if args.reference_url.rstrip("/") != "https://retrostore.org":
        raise ValueError("--reference-url must be exactly https://retrostore.org")
    with ExitStack() as stack:
        reference = stack.enter_context(
            httpx.Client(
                base_url=args.reference_url,
                follow_redirects=False,
                timeout=args.timeout_seconds,
            )
        )
        if args.candidate_url is None:
            if (
                args.public_candidate
                or args.candidate_host_header is not None
                or args.candidate_audience is not None
                or args.candidate_gcloud_identity_token_service_account is not None
            ):
                raise ValueError("Candidate options require --candidate-url")
            app = create_archive_app(
                args.archive,
                {"TESTING": True, "RETROSTORE_REQUEST_LOGGING": False},
            )
            candidate_label = "in-process-normalized-catalog-archive"
            candidate = stack.enter_context(
                httpx.Client(
                    transport=httpx.WSGITransport(app=app),
                    base_url="http://normalized-candidate.test",
                    follow_redirects=False,
                    timeout=args.timeout_seconds,
                )
            )
        else:
            headers: Mapping[str, str] | None
            if args.public_candidate:
                if (
                    args.candidate_host_header is not None
                    or args.candidate_audience is not None
                    or args.candidate_gcloud_identity_token_service_account is not None
                ):
                    raise ValueError(
                        "The public Worker candidate cannot use an override or "
                        "private authentication"
                    )
                candidate_label = _public_candidate_origin(args.candidate_url)
                headers = None
            elif args.candidate_host_header is not None:
                if (
                    args.candidate_audience is not None
                    or args.candidate_gcloud_identity_token_service_account is not None
                ):
                    raise ValueError(
                        "The public front-door probe cannot use private authentication"
                    )
                candidate_label = args.candidate_url.rstrip("/")
                headers = _with_candidate_host_header(
                    candidate_label,
                    args.candidate_host_header,
                )
            else:
                candidate_label = _candidate_origin(args.candidate_url)
                if args.candidate_gcloud_identity_token_service_account != _CANDIDATE_IDENTITY:
                    raise ValueError("The exact private API runtime identity is required")
                audience = args.candidate_audience or candidate_label
                if _candidate_origin(audience) != audience:
                    raise ValueError("Candidate audience must be an approved candidate origin")
                token = _gcloud_identity_token(
                    audience,
                    args.candidate_gcloud_identity_token_service_account,
                )
                headers = {"Authorization": f"Bearer {token}"}
            candidate = stack.enter_context(
                httpx.Client(
                    base_url=candidate_label,
                    headers=headers,
                    follow_redirects=False,
                    timeout=args.timeout_seconds,
                )
            )
        report = compare_public_app_clients(
            reference,
            candidate,
            reference_url=args.reference_url,
            candidate_label=candidate_label,
        )
        if args.candidate_host_header is not None:
            report["candidate_host_header"] = args.candidate_host_header

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"scope": report["scope"], "summary": report["summary"]}))
    return 0 if report["summary"]["passes"] else 1


def _normalize_response(response: httpx.Response) -> dict[str, Any]:
    if len(response.content) > _MAX_RESPONSE_BYTES:
        raise ValueError("Public app-list response exceeds the comparison limit")
    content_type = response.headers.get("content-type", "").partition(";")[0].lower()
    if response.status_code != 200 or content_type != "application/json":
        return {
            "status": response.status_code,
            "content_type": content_type,
            "apps": [],
        }
    try:
        value = response.json()
    except json.JSONDecodeError as error:
        raise ValueError("Public app-list response is not valid JSON") from error
    if not isinstance(value, list) or len(value) > _MAX_APPS:
        raise ValueError("Public app-list response must be a bounded JSON array")
    apps = [_normalize_app(item) for item in value]
    return {"status": 200, "content_type": content_type, "apps": apps}


def _normalize_app(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("Public app-list entry must be an object")
    keys = frozenset(value)
    if not keys >= _REQUIRED_FIELDS or not keys <= _REQUIRED_FIELDS | _OPTIONAL_FIELDS:
        raise ValueError("Public app-list entry has unexpected fields")
    result: dict[str, object] = {}
    for field in _REQUIRED_FIELDS - {"screenshots"}:
        item = value.get(field)
        if not isinstance(item, str):
            raise ValueError(f"Public app-list {field} must be a string")
        result[field] = item
    screenshots = value.get("screenshots")
    if (
        not isinstance(screenshots, list)
        or len(screenshots) > _MAX_SCREENSHOTS
        or not all(isinstance(item, str) for item in screenshots)
    ):
        raise ValueError("Public app-list screenshots must be a bounded string array")
    result["screenshots"] = screenshots
    if "emulatorAppId" in value:
        emulator_app_id = value["emulatorAppId"]
        if not isinstance(emulator_app_id, str):
            raise ValueError("Public app-list emulatorAppId must be a string")
        result["emulatorAppId"] = emulator_app_id
    return result


def _differences(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> list[dict[str, Any]]:
    differences: list[dict[str, Any]] = []
    for field in ("status", "content_type"):
        if expected[field] != actual[field]:
            differences.append({"scope": "response", "field": field})
    expected_apps = expected["apps"]
    actual_apps = actual["apps"]
    if len(expected_apps) != len(actual_apps):
        differences.append({"scope": "response", "field": "app_count"})
    for position, (expected_app, actual_app) in enumerate(
        zip(expected_apps, actual_apps, strict=False)
    ):
        fields = sorted(
            field
            for field in set(expected_app) | set(actual_app)
            if expected_app.get(field) != actual_app.get(field)
        )
        if fields:
            token_source = str(expected_app.get("downloadUrl", position)).encode()
            differences.append(
                {
                    "scope": "entry",
                    "position": position,
                    "entry_token": hashlib.sha256(token_source).hexdigest()[:16],
                    "fields": fields,
                }
            )
    return differences


def _json_sha256(value: object) -> str:
    body = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(body).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())

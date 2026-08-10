"""Compare every legacy public download semantically with the normalized mirror."""

import argparse
import hashlib
import json
import re
import zipfile
from collections.abc import Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

from retrostore.contract.exhaustive import _gcloud_identity_token
from retrostore.mirror import CatalogMirror, load_catalog_mirror_archive
from services.api_compat.app import create_archive_app

_MAX_ZIP_ENTRIES = 64
_MAX_RESPONSE_BYTES = 32 * 1024 * 1024
_CANDIDATE_HOST = "retrostore-api-compat-candidate-760396810462.us-central1.run.app"
_CANDIDATE_IDENTITY = "retrostore-api@trs-80.iam.gserviceaccount.com"
_TAGGED_CANDIDATE_HOST = re.compile(
    r"^[a-z0-9-]+---retrostore-api-compat-candidate-760396810462\.us-central1\.run\.app$"
)


@dataclass(frozen=True, slots=True)
class DownloadScenario:
    id: str
    path: str
    zip_response: bool


def discover_download_scenarios(mirror: CatalogMirror) -> tuple[DownloadScenario, ...]:
    scenarios = [
        DownloadScenario("missing-app-id", "/downloadapp", False),
        DownloadScenario(
            "unknown-app-id",
            "/downloadapp?" + urlencode({"appId": "not-a-real-app"}),
            False,
        ),
    ]
    for app in sorted(mirror.apps, key=lambda item: item.id):
        app_token = hashlib.sha256(app.id.encode()).hexdigest()[:16]
        scenarios.append(
            DownloadScenario(
                f"app-{app_token}-zip",
                "/downloadapp?" + urlencode({"appId": app.id}),
                True,
            )
        )
        extensions = {
            extension
            for media in mirror.media.values()
            if media.app_id == app.id
            if (extension := _filename_extension(media.filename)) is not None
        }
        for extension in sorted(extensions):
            extension_token = hashlib.sha256(extension.encode()).hexdigest()[:8]
            scenarios.append(
                DownloadScenario(
                    f"app-{app_token}-type-{extension_token}",
                    "/downloadapp?"
                    + urlencode({"appId": app.id, "type": extension}),
                    False,
                )
            )
    if mirror.apps:
        app = min(mirror.apps, key=lambda item: item.id)
        app_token = hashlib.sha256(app.id.encode()).hexdigest()[:16]
        scenarios.append(
            DownloadScenario(
                f"app-{app_token}-unknown-type",
                "/downloadapp?"
                + urlencode({"appId": app.id, "type": "not-a-real-type"}),
                False,
            )
        )
    return tuple(scenarios)


def compare_download_clients(
    reference: httpx.Client,
    candidate: httpx.Client,
    scenarios: Sequence[DownloadScenario],
    *,
    reference_url: str,
    candidate_label: str,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    now = generated_at or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")

    differences = []
    matching = 0
    response_bytes = {"reference": 0, "candidate": 0}
    for scenario in scenarios:
        reference_response = reference.get(scenario.path)
        candidate_response = candidate.get(scenario.path)
        response_bytes["reference"] += len(reference_response.content)
        response_bytes["candidate"] += len(candidate_response.content)
        expected = _normalize_response(reference_response, scenario.zip_response)
        actual = _normalize_response(candidate_response, scenario.zip_response)
        fields = _difference_fields(expected, actual)
        if fields:
            differences.append({"scenario": scenario.id, "fields": fields})
        else:
            matching += 1

    return {
        "schema_version": 1,
        "generated_at": now.astimezone(UTC).isoformat(),
        "kind": "retrostore_legacy_download_comparison",
        "reference_url": reference_url,
        "candidate": candidate_label,
        "safety": {
            "read_only": True,
            "contains_app_ids": False,
            "contains_filenames": False,
            "contains_media_bytes": False,
            "contains_credentials": False,
        },
        "scope": {
            "scenario_count": len(scenarios),
            "zip_scenario_count": sum(item.zip_response for item in scenarios),
            "typed_or_error_scenario_count": sum(
                not item.zip_response for item in scenarios
            ),
            "reference_response_bytes": response_bytes["reference"],
            "candidate_response_bytes": response_bytes["candidate"],
        },
        "summary": {
            "total": len(scenarios),
            "matching": matching,
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
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args(argv)

    if args.reference_url.rstrip("/") != "https://retrostore.org":
        raise ValueError("--reference-url must be exactly https://retrostore.org")
    mirror = load_catalog_mirror_archive(args.archive)
    scenarios = discover_download_scenarios(mirror)
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
                args.candidate_audience is not None
                or args.candidate_gcloud_identity_token_service_account is not None
            ):
                raise ValueError("Candidate authentication requires --candidate-url")
            candidate_app = create_archive_app(
                args.archive,
                {"TESTING": True, "RETROSTORE_REQUEST_LOGGING": False},
            )
            candidate_label = "in-process-normalized-catalog-archive"
            candidate = stack.enter_context(
                httpx.Client(
                    transport=httpx.WSGITransport(app=candidate_app),
                    base_url="http://normalized-candidate.test",
                    follow_redirects=False,
                    timeout=args.timeout_seconds,
                )
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
            candidate = stack.enter_context(
                httpx.Client(
                    base_url=candidate_label,
                    headers={"Authorization": f"Bearer {token}"},
                    follow_redirects=False,
                    timeout=args.timeout_seconds,
                )
            )
        report = compare_download_clients(
            reference,
            candidate,
            scenarios,
            reference_url=args.reference_url,
            candidate_label=candidate_label,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"scope": report["scope"], "summary": report["summary"]}))
    return 0 if report["summary"]["passes"] else 1


def _filename_extension(filename: str) -> str | None:
    dot = filename.rfind(".")
    if dot < 0 or dot == len(filename) - 1:
        return None
    return filename[dot + 1 :].casefold()


def _candidate_origin(value: str) -> str:
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or (host != _CANDIDATE_HOST and _TAGGED_CANDIDATE_HOST.fullmatch(host) is None)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Candidate URL must be the approved private Cloud Run origin")
    return f"https://{host}"


def _normalize_response(response: httpx.Response, zip_response: bool) -> dict[str, Any]:
    body = response.content
    if len(body) > _MAX_RESPONSE_BYTES:
        raise ValueError("Legacy download response exceeds the comparison limit")
    result: dict[str, Any] = {
        "status": response.status_code,
        "content_type": response.headers.get("content-type"),
        "content_disposition": response.headers.get("content-disposition"),
        "access_control_allow_origin": response.headers.get(
            "access-control-allow-origin"
        ),
    }
    if zip_response and response.status_code == 200:
        result["zip_entries"] = _normalize_zip(body)
    else:
        result["body_size"] = len(body)
        result["body_sha256"] = hashlib.sha256(body).hexdigest()
    return result


def _normalize_zip(body: bytes) -> list[dict[str, Any]]:
    try:
        with zipfile.ZipFile(BytesIO(body)) as archive:
            entries = archive.infolist()
            if len(entries) > _MAX_ZIP_ENTRIES:
                raise ValueError("Legacy download archive contains too many entries")
            names = [entry.filename for entry in entries]
            if len(names) != len(set(names)):
                raise ValueError("Legacy download archive contains duplicate filenames")
            result = []
            for entry in entries:
                value = archive.read(entry)
                result.append(
                    {
                        "filename_sha256": hashlib.sha256(entry.filename.encode()).hexdigest(),
                        "size": len(value),
                        "sha256": hashlib.sha256(value).hexdigest(),
                    }
                )
            return sorted(result, key=lambda item: item["filename_sha256"])
    except zipfile.BadZipFile as error:
        raise ValueError("Legacy download response is not a valid ZIP archive") from error


def _difference_fields(
    expected: Mapping[str, Any], actual: Mapping[str, Any]
) -> list[str]:
    return sorted(
        key
        for key in set(expected) | set(actual)
        if expected.get(key) != actual.get(key)
    )


if __name__ == "__main__":
    raise SystemExit(main())

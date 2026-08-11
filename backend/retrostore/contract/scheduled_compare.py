"""Run the exhaustive read-only comparator and retain its report in Cloud Storage."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx
from google.auth.transport.requests import Request
from google.cloud import storage
from google.oauth2 import id_token

from retrostore.contract.approvals import evaluate_approvals
from retrostore.contract.exhaustive import compare_exhaustive
from retrostore.contract.legacy_downloads import (
    compare_download_clients,
    discover_download_scenarios_from_reference,
)
from retrostore.contract.public_app_list import compare_public_app_clients
from retrostore.contract.public_redirects import compare_public_redirect_clients
from retrostore.observability import emit_structured_event

_SAFE_PREFIX = re.compile(r"[a-z0-9][a-z0-9/_-]{0,199}/")


class ComparisonArtifactStore(Protocol):
    def create(self, object_name: str, body: bytes) -> str: ...


@dataclass(frozen=True, slots=True)
class ScheduledComparisonConfig:
    project: str
    reference_url: str
    candidate_url: str
    report_bucket: str
    report_prefix: str = "operations/comparisons/"
    timeout_seconds: float = 30.0

    @classmethod
    def from_environment(cls) -> ScheduledComparisonConfig:
        names = {
            "project": "RETROSTORE_PROJECT",
            "reference_url": "RETROSTORE_REFERENCE_URL",
            "candidate_url": "RETROSTORE_CANDIDATE_URL",
            "report_bucket": "RETROSTORE_COMPARISON_BUCKET",
        }
        values = {field: os.environ.get(env_name) for field, env_name in names.items()}
        missing = [env_name for field, env_name in names.items() if not values[field]]
        if missing:
            raise ValueError(f"Scheduled comparison configuration is missing: {', '.join(missing)}")
        config = cls(
            **values,  # type: ignore[arg-type]
            report_prefix=os.environ.get("RETROSTORE_COMPARISON_PREFIX", "operations/comparisons/"),
            timeout_seconds=float(os.environ.get("RETROSTORE_COMPARISON_TIMEOUT", "30")),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.project != "trs-80":
            raise ValueError("Scheduled comparisons are restricted to project trs-80")
        if self.report_bucket != "trs-80-retrostore-assets":
            raise ValueError("Comparison reports must use the approved durable assets bucket")
        if _SAFE_PREFIX.fullmatch(self.report_prefix) is None or not self.report_prefix.startswith(
            "operations/comparisons/"
        ):
            raise ValueError("Comparison report prefix is outside operations/comparisons/")
        for label, value in (
            ("reference", self.reference_url),
            ("candidate", self.candidate_url),
        ):
            parsed = urlsplit(value)
            if (
                parsed.scheme != "https"
                or not parsed.netloc
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(f"Scheduled comparison {label} must be an HTTPS origin")
        if not 1 <= self.timeout_seconds <= 300:
            raise ValueError("Scheduled comparison timeout must be between 1 and 300 seconds")


class CloudStorageComparisonArtifactStore:
    def __init__(self, *, project: str, bucket: str) -> None:
        self._bucket_name = bucket
        self._bucket = storage.Client(project=project).bucket(bucket)

    def create(self, object_name: str, body: bytes) -> str:
        blob = self._bucket.blob(object_name)
        blob.upload_from_string(
            body,
            content_type="application/json",
            if_generation_match=0,
        )
        return f"gs://{self._bucket_name}/{object_name}"


def google_identity_token(audience: str) -> str:
    token = id_token.fetch_id_token(Request(), audience.rstrip("/"))
    if not token:
        raise RuntimeError("Google identity token provider returned an empty token")
    return token


def run_scheduled_comparison(
    config: ScheduledComparisonConfig,
    artifact_store: ComparisonArtifactStore,
    *,
    now: datetime | None = None,
    token_fetcher: Callable[[str], str] = google_identity_token,
    comparator: Callable[..., dict[str, Any]] = compare_exhaustive,
    surface_comparator: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    config.validate()
    generated_at = (now or datetime.now(UTC)).astimezone(UTC)
    candidate_token = token_fetcher(config.candidate_url)
    candidate_headers = {"Authorization": f"Bearer {candidate_token}"}
    report = evaluate_approvals(
        comparator(
            config.reference_url,
            config.candidate_url,
            config.timeout_seconds,
            candidate_headers,
        ),
        (),
        today=generated_at.date(),
    )
    compare_surfaces = surface_comparator or _compare_additional_surfaces
    surface_reports = compare_surfaces(config, candidate_headers, generated_at)
    overall_gate = {
        "passes": (
            report["approval_gate"]["passes"]
            and surface_reports["legacy_downloads"]["summary"]["passes"]
            and surface_reports["public_app_list"]["summary"]["passes"]
            and surface_reports["public_redirects"]["summary"]["passes"]
        ),
        "api_contract_passes": report["approval_gate"]["passes"],
        "legacy_downloads_passes": surface_reports["legacy_downloads"]["summary"]["passes"],
        "public_app_list_passes": surface_reports["public_app_list"]["summary"]["passes"],
        "public_redirects_passes": surface_reports["public_redirects"]["summary"]["passes"],
    }
    artifact = {
        "schema_version": 3,
        "generated_at": generated_at.isoformat(),
        "kind": "retrostore_multi_surface_http_comparison",
        "report": report,
        "surface_reports": surface_reports,
        "overall_gate": overall_gate,
    }
    body = (json.dumps(artifact, indent=2, sort_keys=True) + "\n").encode()
    digest = hashlib.sha256(body).hexdigest()
    timestamp = generated_at.strftime("%Y%m%dT%H%M%S%fZ")
    object_name = f"{config.report_prefix}{generated_at:%Y/%m/%d}/{timestamp}-{digest[:16]}.json"
    artifact_uri = artifact_store.create(object_name, body)
    result = {
        "artifact_uri": artifact_uri,
        "artifact_sha256": digest,
        "generated_at": generated_at.isoformat(),
        "summary": report["summary"],
        "scope": report.get("scope", {}),
        "approval_gate": overall_gate,
    }
    emit_structured_event(
        {
            "event": "scheduled_comparison",
            "service": "retrostore-comparator",
            "severity": "INFO" if overall_gate["passes"] else "ERROR",
            **result,
        }
    )
    return result


def _compare_additional_surfaces(
    config: ScheduledComparisonConfig,
    candidate_headers: dict[str, str],
    generated_at: datetime,
) -> dict[str, Any]:
    with (
        httpx.Client(
            base_url=config.reference_url,
            follow_redirects=False,
            timeout=config.timeout_seconds,
        ) as reference,
        httpx.Client(
            base_url=config.candidate_url,
            headers=candidate_headers,
            follow_redirects=False,
            timeout=config.timeout_seconds,
        ) as candidate,
    ):
        download_scenarios = discover_download_scenarios_from_reference(reference)
        downloads = compare_download_clients(
            reference,
            candidate,
            download_scenarios,
            reference_url=config.reference_url,
            candidate_label=config.candidate_url,
            generated_at=generated_at,
        )
        public_apps = compare_public_app_clients(
            reference,
            candidate,
            reference_url=config.reference_url,
            candidate_label=config.candidate_url,
            generated_at=generated_at,
        )
        public_redirects = compare_public_redirect_clients(
            reference,
            candidate,
            reference_url=config.reference_url,
            candidate_label=config.candidate_url,
            generated_at=generated_at,
        )
    return {
        "legacy_downloads": downloads,
        "public_app_list": public_apps,
        "public_redirects": public_redirects,
    }


def main() -> int:
    config = ScheduledComparisonConfig.from_environment()
    artifact_store = CloudStorageComparisonArtifactStore(
        project=config.project,
        bucket=config.report_bucket,
    )
    result = run_scheduled_comparison(config, artifact_store)
    return 0 if result["approval_gate"]["passes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

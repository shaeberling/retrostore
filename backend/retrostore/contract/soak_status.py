"""Validate retained comparator evidence and calculate its zero-diff streak."""

import argparse
import hashlib
import json
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from google.cloud import storage

from retrostore.google_cloud import gcloud_impersonated_credentials

_PROJECT = "trs-80"
_REGION = "us-central1"
_SERVICE = "retrostore-api-compat-candidate"
_CANDIDATE_URL = "https://retrostore-api-compat-candidate-760396810462.us-central1.run.app"
_BUCKET = "trs-80-retrostore-assets"
_PREFIX = "operations/comparisons/"
_READER = "retrostore-migrator@trs-80.iam.gserviceaccount.com"
_MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
_OBJECT_NAME = re.compile(
    r"operations/comparisons/(\d{4})/(\d{2})/(\d{2})/"
    r"(\d{8}T\d{12}Z)-([0-9a-f]{16})\.json"
)


@dataclass(frozen=True, slots=True)
class ComparisonEvidence:
    generated_at: datetime
    object_name: str
    sha256: str
    total: int
    matching: int
    different: int
    difference_fields: int
    approval_gate_passes: bool
    additional_surfaces_pass: bool

    @property
    def api_zero_diff_passes(self) -> bool:
        return (
            self.approval_gate_passes
            and self.total >= 158
            and self.matching == self.total
            and self.different == 0
            and self.difference_fields == 0
        )

    @property
    def zero_diff_passes(self) -> bool:
        return self.api_zero_diff_passes and self.additional_surfaces_pass


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--thresholds", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-project")
    parser.add_argument("--confirm-service")
    parser.add_argument("--confirm-revision")
    parser.add_argument("--require-current", action="store_true")
    args = parser.parse_args(argv)

    policy = _load_policy(args.thresholds)
    baseline = _load_baseline(args.baseline)
    revision = baseline["revision"]
    not_before = _parse_timestamp(baseline["soak_not_before"], "soak_not_before")
    if not args.apply:
        report: dict[str, Any] = {
            "schema_version": 1,
            "operation": "private_api_zero_diff_soak_status",
            "applied": False,
            "read_only": True,
            "source": {"bucket": _BUCKET, "prefix": _PREFIX},
            "project": _PROJECT,
            "region": _REGION,
            "service": _SERVICE,
            "revision": revision,
            "soak_not_before": not_before.isoformat(),
            "policy": policy,
        }
    else:
        _validate_confirmations(args, revision)
        _require_gcloud_project()
        revision_evidence = _verify_service_revision(revision)
        credentials = gcloud_impersonated_credentials(
            project=_PROJECT,
            service_account=_READER,
        )
        client = storage.Client(project=_PROJECT, credentials=credentials)
        evidence = _load_cloud_evidence(client)
        now = datetime.now(UTC)
        soak = evaluate_soak(
            evidence,
            not_before=not_before,
            as_of=now,
            schedule_seconds=policy["schedule_seconds"],
            required_reports=policy["required_reports"],
        )
        report = {
            "schema_version": 1,
            "operation": "private_api_zero_diff_soak_status",
            "applied": True,
            "read_only": True,
            "generated_at": now.isoformat(),
            "source": {"bucket": _BUCKET, "prefix": _PREFIX},
            "project": _PROJECT,
            "region": _REGION,
            "service": _SERVICE,
            "revision": revision,
            "revision_evidence": revision_evidence,
            "soak_not_before": not_before.isoformat(),
            "policy": policy,
            "artifacts": {
                "validated_count": len(evidence),
                "before_boundary_count": sum(item.generated_at < not_before for item in evidence),
                "at_or_after_boundary_count": sum(
                    item.generated_at >= not_before for item in evidence
                ),
                "api_zero_diff_count": sum(item.api_zero_diff_passes for item in evidence),
                "multi_surface_zero_diff_count": sum(item.zero_diff_passes for item in evidence),
                "not_multi_surface_eligible_count": sum(
                    not item.zero_diff_passes for item in evidence
                ),
                "latest": _evidence_reference(evidence[-1]) if evidence else None,
            },
            "soak": soak,
            "safety": {
                "contains_comparison_results": False,
                "contains_catalog_field_values": False,
                "contains_request_or_response_payloads": False,
                "contains_credentials": False,
                "contains_state_tokens": False,
                "cloud_requests_are_read_only": True,
            },
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(_console_summary(report), sort_keys=True, separators=(",", ":")))
    if args.apply and args.require_current and not report["soak"]["current"]:
        return 1
    return 0


def parse_comparison_artifact(object_name: str, body: bytes) -> ComparisonEvidence:
    match = _OBJECT_NAME.fullmatch(object_name)
    if match is None:
        raise ValueError(f"Invalid comparison artifact path: {object_name}")
    if not body or len(body) > _MAX_ARTIFACT_BYTES:
        raise ValueError(f"Comparison artifact has an invalid size: {object_name}")
    digest = hashlib.sha256(body).hexdigest()
    if digest[:16] != match.group(5):
        raise ValueError(f"Comparison artifact digest does not match its name: {object_name}")
    try:
        artifact = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Comparison artifact is not valid UTF-8 JSON: {object_name}") from error
    if not isinstance(artifact, dict):
        raise ValueError(f"Comparison artifact root is not an object: {object_name}")
    schema_version = artifact.get("schema_version")
    if schema_version not in {1, 2, 3}:
        raise ValueError(f"Unsupported comparison artifact schema: {object_name}")
    expected_kind = (
        "retrostore_exhaustive_http_comparison"
        if schema_version == 1
        else "retrostore_multi_surface_http_comparison"
    )
    if artifact.get("kind") != expected_kind:
        raise ValueError(f"Unexpected comparison artifact kind: {object_name}")
    generated_at = _parse_timestamp(artifact.get("generated_at"), "generated_at")
    expected_timestamp = generated_at.strftime("%Y%m%dT%H%M%S%fZ")
    if match.group(4) != expected_timestamp:
        raise ValueError(f"Comparison artifact timestamp does not match its name: {object_name}")
    if (match.group(1), match.group(2), match.group(3)) != (
        generated_at.strftime("%Y"),
        generated_at.strftime("%m"),
        generated_at.strftime("%d"),
    ):
        raise ValueError(f"Comparison artifact date path is inconsistent: {object_name}")

    report = artifact.get("report")
    if not isinstance(report, dict):
        raise ValueError(f"Comparison artifact report is missing: {object_name}")
    if report.get("schema_version") != 1:
        raise ValueError(f"Unsupported comparison report schema: {object_name}")
    if report.get("reference_url") != "https://retrostore.org":
        raise ValueError(f"Comparison reference URL is unexpected: {object_name}")
    if report.get("candidate_url") != _CANDIDATE_URL:
        raise ValueError(f"Comparison candidate URL is unexpected: {object_name}")

    summary = report.get("summary")
    scope = report.get("scope")
    gate = report.get("approval_gate")
    results = report.get("results")
    if not all(isinstance(value, dict) for value in (summary, scope, gate)):
        raise ValueError(f"Comparison artifact summaries are invalid: {object_name}")
    if not isinstance(results, list):
        raise ValueError(f"Comparison artifact results are invalid: {object_name}")
    total = _nonnegative_int(summary.get("total"), "summary.total", object_name)
    matching = _nonnegative_int(summary.get("matching"), "summary.matching", object_name)
    different = _nonnegative_int(summary.get("different"), "summary.different", object_name)
    scenario_count = _nonnegative_int(
        scope.get("scenario_count"), "scope.scenario_count", object_name
    )
    if total != scenario_count or total != len(results) or matching + different != total:
        raise ValueError(f"Comparison artifact counts are inconsistent: {object_name}")

    computed_different = 0
    computed_difference_fields = 0
    for result in results:
        if not isinstance(result, dict) or not isinstance(result.get("differences"), dict):
            raise ValueError(f"Comparison result is invalid: {object_name}")
        differences = result["differences"]
        computed_different += bool(differences)
        computed_difference_fields += len(differences)
    if different != computed_different or matching != total - computed_different:
        raise ValueError(f"Comparison result counts do not match summary: {object_name}")

    difference_fields = _nonnegative_int(
        gate.get("difference_fields"), "approval_gate.difference_fields", object_name
    )
    unapproved = _nonnegative_int(gate.get("unapproved"), "approval_gate.unapproved", object_name)
    expired = _nonnegative_int(
        gate.get("expired_approvals"), "approval_gate.expired_approvals", object_name
    )
    stale = _nonnegative_int(
        gate.get("stale_approvals"), "approval_gate.stale_approvals", object_name
    )
    gate_passes = gate.get("passes")
    if not isinstance(gate_passes, bool):
        raise ValueError(f"Comparison approval gate is invalid: {object_name}")
    if difference_fields != computed_difference_fields:
        raise ValueError(f"Comparison difference-field count is inconsistent: {object_name}")
    if gate_passes != (unapproved == 0 and expired == 0 and stale == 0):
        raise ValueError(f"Comparison approval result is inconsistent: {object_name}")
    additional_surfaces_pass = False
    if schema_version in {2, 3}:
        additional_surfaces_pass = _validate_additional_surfaces(
            artifact,
            object_name=object_name,
            api_gate_passes=gate_passes,
            require_public_redirects=schema_version == 3,
        )
    return ComparisonEvidence(
        generated_at=generated_at,
        object_name=object_name,
        sha256=digest,
        total=total,
        matching=matching,
        different=different,
        difference_fields=difference_fields,
        approval_gate_passes=gate_passes,
        additional_surfaces_pass=additional_surfaces_pass,
    )


def _validate_additional_surfaces(
    artifact: Mapping[str, Any],
    *,
    object_name: str,
    api_gate_passes: bool,
    require_public_redirects: bool,
) -> bool:
    reports = artifact.get("surface_reports")
    overall = artifact.get("overall_gate")
    if not isinstance(reports, Mapping) or not isinstance(overall, Mapping):
        raise ValueError(f"Comparison surface reports are missing: {object_name}")
    downloads = reports.get("legacy_downloads")
    public_apps = reports.get("public_app_list")
    if not isinstance(downloads, Mapping) or not isinstance(public_apps, Mapping):
        raise ValueError(f"Comparison surface report is invalid: {object_name}")

    download_summary = downloads.get("summary")
    download_scope = downloads.get("scope")
    download_differences = downloads.get("differences")
    if (
        downloads.get("schema_version") != 1
        or downloads.get("kind") != "retrostore_legacy_download_comparison"
        or downloads.get("reference_url") != "https://retrostore.org"
        or downloads.get("candidate") != _CANDIDATE_URL
        or not isinstance(download_summary, Mapping)
        or not isinstance(download_scope, Mapping)
        or not isinstance(download_differences, list)
    ):
        raise ValueError(f"Legacy download surface report is malformed: {object_name}")
    download_total = _nonnegative_int(
        download_summary.get("total"), "downloads.summary.total", object_name
    )
    download_matching = _nonnegative_int(
        download_summary.get("matching"), "downloads.summary.matching", object_name
    )
    download_different = _nonnegative_int(
        download_summary.get("different"), "downloads.summary.different", object_name
    )
    download_scenarios = _nonnegative_int(
        download_scope.get("scenario_count"), "downloads.scope.scenario_count", object_name
    )
    download_passes = download_summary.get("passes")
    if (
        not isinstance(download_passes, bool)
        or download_total != download_scenarios
        or download_matching + download_different != download_total
        or download_different != len(download_differences)
        or download_passes != (download_different == 0)
    ):
        raise ValueError(f"Legacy download surface counts are inconsistent: {object_name}")

    public_summary = public_apps.get("summary")
    public_scope = public_apps.get("scope")
    public_differences = public_apps.get("differences")
    if (
        public_apps.get("schema_version") != 1
        or public_apps.get("kind") != "retrostore_public_website_app_list_comparison"
        or public_apps.get("reference_url") != "https://retrostore.org"
        or public_apps.get("candidate") != _CANDIDATE_URL
        or not isinstance(public_summary, Mapping)
        or not isinstance(public_scope, Mapping)
        or not isinstance(public_differences, list)
    ):
        raise ValueError(f"Public app-list surface report is malformed: {object_name}")
    public_different = _nonnegative_int(
        public_summary.get("different"), "public_apps.summary.different", object_name
    )
    reference_count = _nonnegative_int(
        public_scope.get("reference_app_count"),
        "public_apps.scope.reference_app_count",
        object_name,
    )
    candidate_count = _nonnegative_int(
        public_scope.get("candidate_app_count"),
        "public_apps.scope.candidate_app_count",
        object_name,
    )
    public_passes = public_summary.get("passes")
    if (
        not isinstance(public_passes, bool)
        or public_different != len(public_differences)
        or public_passes != (public_different == 0 and reference_count == candidate_count)
    ):
        raise ValueError(f"Public app-list surface counts are inconsistent: {object_name}")

    redirect_passes = True
    if require_public_redirects:
        redirects = reports.get("public_redirects")
        if not isinstance(redirects, Mapping):
            raise ValueError(f"Public redirect surface report is missing: {object_name}")
        redirect_summary = redirects.get("summary")
        redirect_scope = redirects.get("scope")
        redirect_differences = redirects.get("differences")
        redirect_results = redirects.get("results")
        if (
            redirects.get("schema_version") != 1
            or redirects.get("kind") != "retrostore_public_redirect_comparison"
            or redirects.get("reference_url") != "https://retrostore.org"
            or redirects.get("candidate") != _CANDIDATE_URL
            or not isinstance(redirect_summary, Mapping)
            or not isinstance(redirect_scope, Mapping)
            or not isinstance(redirect_differences, list)
            or not isinstance(redirect_results, list)
        ):
            raise ValueError(f"Public redirect surface report is malformed: {object_name}")
        redirect_total = _nonnegative_int(
            redirect_summary.get("total"), "redirects.summary.total", object_name
        )
        redirect_matching = _nonnegative_int(
            redirect_summary.get("matching"), "redirects.summary.matching", object_name
        )
        redirect_different = _nonnegative_int(
            redirect_summary.get("different"), "redirects.summary.different", object_name
        )
        redirect_scenarios = _nonnegative_int(
            redirect_scope.get("scenario_count"),
            "redirects.scope.scenario_count",
            object_name,
        )
        redirect_passes_value = redirect_summary.get("passes")
        expected_redirect_paths = {
            "/community",
            "/community/",
            "/rsc",
            "/rsc/",
            "/app",
            "/app/",
        }
        if (
            not all(
                isinstance(result, Mapping)
                and isinstance(result.get("path"), str)
                and isinstance(result.get("matches"), bool)
                and isinstance(result.get("reference"), Mapping)
                and isinstance(result.get("candidate"), Mapping)
                for result in redirect_results
            )
            or {result["path"] for result in redirect_results} != expected_redirect_paths
        ):
            raise ValueError(f"Public redirect results are inconsistent: {object_name}")
        result_different = sum(not result["matches"] for result in redirect_results)
        if (
            not isinstance(redirect_passes_value, bool)
            or redirect_total != 6
            or redirect_total != redirect_scenarios
            or redirect_total != len(redirect_results)
            or redirect_matching + redirect_different != redirect_total
            or redirect_different != len(redirect_differences)
            or redirect_different != result_different
            or redirect_passes_value != (redirect_different == 0)
        ):
            raise ValueError(f"Public redirect surface counts are inconsistent: {object_name}")
        redirect_passes = redirect_passes_value

    expected_overall = {
        "passes": (api_gate_passes and download_passes and public_passes and redirect_passes),
        "api_contract_passes": api_gate_passes,
        "legacy_downloads_passes": download_passes,
        "public_app_list_passes": public_passes,
    }
    if require_public_redirects:
        expected_overall["public_redirects_passes"] = redirect_passes
    if dict(overall) != expected_overall:
        raise ValueError(f"Comparison overall gate is inconsistent: {object_name}")
    return download_passes and public_passes and redirect_passes


def evaluate_soak(
    evidence: Sequence[ComparisonEvidence],
    *,
    not_before: datetime,
    as_of: datetime,
    schedule_seconds: int,
    required_reports: int,
) -> dict[str, Any]:
    not_before = not_before.astimezone(UTC)
    as_of = as_of.astimezone(UTC)
    maximum_gap_seconds = int(schedule_seconds * 1.5)
    relevant = sorted(
        (item for item in evidence if not_before <= item.generated_at <= as_of),
        key=lambda item: item.generated_at,
    )
    streak: list[ComparisonEvidence] = []
    latest_age_seconds: float | None = None
    if relevant:
        latest_age_seconds = (as_of - relevant[-1].generated_at).total_seconds()
        if relevant[-1].zero_diff_passes and latest_age_seconds <= maximum_gap_seconds:
            streak.append(relevant[-1])
            newer = relevant[-1]
            for item in reversed(relevant[:-1]):
                gap = (newer.generated_at - item.generated_at).total_seconds()
                if not item.zero_diff_passes or gap > maximum_gap_seconds:
                    break
                streak.append(item)
                newer = item
            streak.reverse()

    gaps = [
        (right.generated_at - left.generated_at).total_seconds()
        for left, right in zip(streak, streak[1:], strict=False)
    ]
    duration_seconds = (as_of - streak[0].generated_at).total_seconds() if streak else 0.0
    current = bool(streak)
    eligible = current and len(streak) >= required_reports
    reasons = []
    if not relevant:
        reasons.append("no_reports_at_or_after_boundary")
    elif not relevant[-1].zero_diff_passes:
        reasons.append("latest_report_is_not_zero_diff")
    elif latest_age_seconds is not None and latest_age_seconds > maximum_gap_seconds:
        reasons.append("latest_report_is_stale")
    if current and not eligible:
        reasons.append("required_report_count_not_reached")
    return {
        "current": current,
        "eligible": eligible,
        "required_reports": required_reports,
        "schedule_seconds": schedule_seconds,
        "maximum_gap_seconds": maximum_gap_seconds,
        "report_count": len(streak),
        "started_at": streak[0].generated_at.isoformat() if streak else None,
        "latest_at": streak[-1].generated_at.isoformat() if streak else None,
        "latest_age_seconds": latest_age_seconds,
        "duration_seconds": duration_seconds,
        "maximum_observed_gap_seconds": max(gaps) if gaps else 0.0,
        "reasons": reasons,
    }


def _load_cloud_evidence(client: storage.Client) -> tuple[ComparisonEvidence, ...]:
    evidence = []
    for blob in client.list_blobs(_BUCKET, prefix=_PREFIX):
        if blob.size is None or blob.size <= 0 or blob.size > _MAX_ARTIFACT_BYTES:
            raise ValueError(f"Comparison object has an invalid size: {blob.name}")
        if blob.generation is None:
            raise ValueError(f"Comparison object has no generation: {blob.name}")
        body = blob.download_as_bytes(
            if_generation_match=int(blob.generation),
            checksum="auto",
        )
        if len(body) != blob.size:
            raise ValueError(f"Comparison object size changed during download: {blob.name}")
        evidence.append(parse_comparison_artifact(blob.name, body))
    return tuple(sorted(evidence, key=lambda item: item.generated_at))


def _load_policy(path: Path) -> dict[str, int]:
    value = json.loads(path.read_text())
    comparison = value.get("comparison") if isinstance(value, dict) else None
    if value.get("schema_version") != 1 or not isinstance(comparison, dict):
        raise ValueError("Monitoring thresholds have an unsupported schema")
    schedule = comparison.get("schedule_seconds")
    reports = comparison.get("minimum_consecutive_zero_diff_reports")
    maximum_differences = comparison.get("maximum_unexplained_differences")
    maximum_unapproved = comparison.get("maximum_unapproved_differences")
    if (
        not isinstance(schedule, int)
        or schedule != 3600
        or not isinstance(reports, int)
        or reports < 3
        or maximum_differences != 0
        or maximum_unapproved != 0
        or comparison.get("material_fix_restarts_evidence_streak") is not True
    ):
        raise ValueError("Monitoring thresholds do not enforce the approved evidence policy")
    return {"schedule_seconds": schedule, "required_reports": reports}


def _load_baseline(path: Path) -> dict[str, str]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("Private soak baseline has an unsupported schema")
    expected = {
        "status": "private_evidence_only_no_cutover_authority",
        "project": _PROJECT,
        "region": _REGION,
        "service": _SERVICE,
        "candidate_url": _CANDIDATE_URL,
        "production_routing_changed": False,
        "catalog_activation_authorized": False,
        "load_balancer_authorized": False,
        "evidence_schema_version": 3,
        "comparator_job_generation": 4,
        "comparator_image_digest": (
            "sha256:22d135c40f50ec10649f9a8480ad9898dbceb52a6c2628cbad1f73ac93bed3d4"
        ),
    }
    if any(value.get(key) != expected_value for key, expected_value in expected.items()):
        raise ValueError("Private soak baseline violates its safety boundary")
    if value.get("required_surfaces") != [
        "frozen_api",
        "legacy_downloads",
        "public_app_list",
        "public_redirects",
    ]:
        raise ValueError("Private soak baseline does not require all public read surfaces")
    revision = value.get("revision")
    _validate_revision(revision)
    ready_at = _parse_timestamp(value.get("revision_ready_at"), "revision_ready_at")
    not_before = _parse_timestamp(value.get("soak_not_before"), "soak_not_before")
    if not_before < ready_at:
        raise ValueError("Private soak boundary predates revision readiness")
    return {"revision": revision, "soak_not_before": not_before.isoformat()}


def _verify_service_revision(revision: str) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "gcloud",
            "run",
            "services",
            "describe",
            _SERVICE,
            "--project",
            _PROJECT,
            "--region",
            _REGION,
            "--format=json(metadata.generation,status.latestReadyRevisionName,status.traffic)",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    value = json.loads(completed.stdout)
    status = value.get("status", {})
    traffic = status.get("traffic", ())
    if status.get("latestReadyRevisionName") != revision or not isinstance(traffic, list):
        raise RuntimeError("Private candidate latest-ready revision is not the expected revision")
    serving_percent = sum(
        item.get("percent", 0)
        for item in traffic
        if isinstance(item, dict) and item.get("revisionName") == revision
    )
    other_percent = sum(
        item.get("percent", 0)
        for item in traffic
        if isinstance(item, dict) and item.get("revisionName") != revision
    )
    if serving_percent != 100 or other_percent != 0:
        raise RuntimeError("Private candidate is not serving 100% from the expected revision")
    return {
        "service_generation": value.get("metadata", {}).get("generation"),
        "latest_ready_revision": revision,
        "expected_revision_traffic_percent": serving_percent,
        "other_revision_traffic_percent": other_percent,
    }


def _require_gcloud_project() -> None:
    completed = subprocess.run(
        ["gcloud", "config", "get-value", "project", "--quiet"],
        check=True,
        capture_output=True,
        text=True,
    )
    if completed.stdout.strip() != _PROJECT:
        raise RuntimeError(f"gcloud must be configured for exactly {_PROJECT}")


def _validate_confirmations(args: argparse.Namespace, revision: str) -> None:
    if args.confirm_project != _PROJECT:
        raise ValueError(f"--confirm-project must be exactly {_PROJECT}")
    if args.confirm_service != _SERVICE:
        raise ValueError(f"--confirm-service must be exactly {_SERVICE}")
    if args.confirm_revision != revision:
        raise ValueError("--confirm-revision must exactly match the checked-in baseline")


def _validate_revision(revision: object) -> None:
    if (
        not isinstance(revision, str)
        or not revision.startswith(f"{_SERVICE}-")
        or not re.fullmatch(r"[a-z0-9-]+", revision)
    ):
        raise ValueError("Soak revision must belong to the private API candidate")


def _parse_timestamp(value: Any, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an ISO timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must include a timezone")
    return parsed.astimezone(UTC)


def _nonnegative_int(value: Any, name: str, object_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"Comparison {name} is invalid: {object_name}")
    return value


def _evidence_reference(item: ComparisonEvidence) -> dict[str, Any]:
    return {
        "generated_at": item.generated_at.isoformat(),
        "object_name": item.object_name,
        "sha256": item.sha256,
        "total": item.total,
        "matching": item.matching,
        "different": item.different,
        "difference_fields": item.difference_fields,
        "approval_gate_passes": item.approval_gate_passes,
        "additional_surfaces_pass": item.additional_surfaces_pass,
        "api_zero_diff_passes": item.api_zero_diff_passes,
        "zero_diff_passes": item.zero_diff_passes,
    }


def _console_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    if not report.get("applied"):
        return {
            "applied": False,
            "service": report["service"],
            "revision": report["revision"],
            "soak_not_before": report["soak_not_before"],
            "policy": report["policy"],
        }
    return {
        "applied": True,
        "revision": report["revision"],
        "artifacts": report["artifacts"],
        "soak": report["soak"],
    }


if __name__ == "__main__":
    raise SystemExit(main())

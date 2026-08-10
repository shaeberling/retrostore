"""Combine sanitized evidence and operator decisions into fail-closed readiness."""

import argparse
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from retrostore.contracts import PUBLIC_API_METHODS

_REVISION = "retrostore-api-compat-candidate-redirects1"
_PUBLIC_RESOURCE_DECISIONS = frozenset(
    {
        "candidate_hostnames",
        "go_no_go_owner",
        "rollback_operator",
    }
)
_PRODUCTION_CUTOVER_DECISIONS = _PUBLIC_RESOURCE_DECISIONS | {"alert_destination"}


def evaluate_migration_readiness(
    *,
    decisions: Mapping[str, Any],
    soak: Mapping[str, Any],
    candidates: Mapping[str, Any],
    comparator: Mapping[str, Any],
    consumers: Mapping[str, Any],
    public_transport: Mapping[str, Any],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    now = generated_at or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")
    pending = _pending_decisions(decisions)
    checks = {
        "comparison_evidence_is_current": _soak_current(soak),
        "private_candidates_match_baseline": _summary_passes(
            candidates, "private_cloud_run_candidate_drift_audit"
        ),
        "comparator_pipeline_matches_baseline": _summary_passes(
            comparator, "scheduled_comparator_runtime_drift_audit"
        ),
        "pinned_consumers_pass": _consumer_gate_passes(consumers),
        "public_http_https_338_pass": _public_transport_passes(public_transport),
    }
    engineering_passes = all(checks.values())
    soak_eligible = _soak_eligible(soak)
    public_resource_blockers = sorted(pending & _PUBLIC_RESOURCE_DECISIONS)
    production_cutover_blockers = sorted(pending & _PRODUCTION_CUTOVER_DECISIONS)
    if not soak_eligible:
        production_cutover_blockers.append("private_zero_diff_evidence_not_ready")
    if not engineering_passes:
        production_cutover_blockers.extend(
            f"evidence:{name}" for name, passes in checks.items() if not passes
        )
    retirement_blockers = sorted(pending)
    if not soak_eligible:
        retirement_blockers.append("private_zero_diff_evidence_not_ready")
    if not engineering_passes:
        retirement_blockers.extend(
            f"evidence:{name}" for name, passes in checks.items() if not passes
        )
    return {
        "schema_version": 1,
        "generated_at": now.astimezone(UTC).isoformat(),
        "operation": "local_migration_readiness_evaluation",
        "applied": False,
        "project": "trs-80",
        "revision": _REVISION,
        "evidence": {
            "checks": checks,
            "passes": engineering_passes,
            "comparison_evidence": {
                "current": soak["soak"]["current"],
                "eligible": soak["soak"]["eligible"],
                "report_count": soak["soak"]["report_count"],
                "required_reports": soak["soak"]["required_reports"],
                "started_at": soak["soak"]["started_at"],
                "latest_at": soak["soak"]["latest_at"],
                "reasons": soak["soak"]["reasons"],
            },
        },
        "decisions": {
            "pending_count": len(pending),
            "pending_ids": sorted(pending),
        },
        "gates": {
            "private_engineering_evidence": {
                "passes": engineering_passes,
                "blockers": sorted(name for name, value in checks.items() if not value),
            },
            "public_resource_creation": {
                "passes": not public_resource_blockers,
                "blockers": public_resource_blockers,
            },
            "production_cutover": {
                "passes": not production_cutover_blockers,
                "blockers": sorted(set(production_cutover_blockers)),
                "requires_runtime_operator_approval": True,
            },
            "app_engine_retirement": {
                "passes": not retirement_blockers,
                "blockers": sorted(set(retirement_blockers)),
            },
        },
        "safety": {
            "local_files_only": True,
            "cloud_requests_made": False,
            "mutation_or_cutover_capability_present": False,
            "contains_credentials": False,
            "contains_payloads_or_catalog_values": False,
            "authorizes_public_resources_or_traffic": False,
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--soak", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--comparator", type=Path, required=True)
    parser.add_argument("--consumers", type=Path, required=True)
    parser.add_argument("--public-transport", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-production-cutover-ready", action="store_true")
    args = parser.parse_args(argv)
    if args.output.exists():
        raise FileExistsError(f"Readiness output already exists: {args.output}")
    report = evaluate_migration_readiness(
        decisions=_load(args.decisions),
        soak=_load(args.soak),
        candidates=_load(args.candidates),
        comparator=_load(args.comparator),
        consumers=_load(args.consumers),
        public_transport=_load(args.public_transport),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "evidence_passes": report["evidence"]["passes"],
                "gates": report["gates"],
                "pending_decision_count": report["decisions"]["pending_count"],
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    if (
        args.require_production_cutover_ready
        and not report["gates"]["production_cutover"]["passes"]
    ):
        return 1
    return 0


def _pending_decisions(decisions: Mapping[str, Any]) -> set[str]:
    if (
        decisions.get("schema_version") != 1
        or decisions.get("status")
        != "candidate_public_resources_approved_no_production_authority"
    ):
        raise ValueError("Migration decision register identity is invalid")
    pending = decisions.get("pending")
    if not isinstance(pending, list) or not pending:
        raise ValueError("Migration decision register has no pending decisions")
    if any(item.get("status") != "confirmation_required" for item in pending):
        raise ValueError("Migration decision register contains an unvalidated decision")
    ids = {item["id"] for item in pending}
    if len(ids) != len(pending):
        raise ValueError("Migration decision IDs are not unique")
    return ids


def _soak_current(soak: Mapping[str, Any]) -> bool:
    _validate_applied_report(soak, "private_api_zero_diff_soak_status")
    _require_safety_false(
        soak,
        {
            "contains_catalog_field_values",
            "contains_comparison_results",
            "contains_credentials",
            "contains_request_or_response_payloads",
            "contains_state_tokens",
        },
    )
    if soak.get("revision") != _REVISION:
        raise ValueError("Soak report revision is not the pinned private candidate")
    value = soak.get("soak")
    if not isinstance(value, dict):
        raise ValueError("Soak report has no status")
    return (
        value.get("current") is True
        and value.get("required_reports") == 3
        and value.get("report_count", 0) >= 1
    )


def _soak_eligible(soak: Mapping[str, Any]) -> bool:
    return (
        _soak_current(soak)
        and soak["soak"].get("eligible") is True
        and soak["soak"].get("report_count", 0) >= 3
    )


def _summary_passes(report: Mapping[str, Any], operation: str) -> bool:
    _validate_applied_report(report, operation)
    summary = report.get("summary")
    if not isinstance(summary, dict):
        raise ValueError(f"{operation} has no summary")
    if operation == "private_cloud_run_candidate_drift_audit":
        _require_safety_false(
            report,
            {
                "contains_credentials",
                "contains_environment_values",
                "contains_invoker_member_values",
                "production_routing_changed",
                "public_iam_changed",
            },
        )
        expected = summary.get("service_count") == summary.get("passing") == 3
    else:
        _require_safety_false(
            report,
            {
                "contains_comparison_payloads",
                "contains_credentials",
                "contains_environment_values",
                "contains_iam_member_values",
                "production_routing_changed",
            },
        )
        expected = summary.get("check_count") == summary.get("passing") == 9
    return summary.get("passes") is True and summary.get("failing") == 0 and expected


def _consumer_gate_passes(report: Mapping[str, Any]) -> bool:
    _validate_applied_report(report, "deployed_private_consumer_client_gate")
    _require_safety_false(
        report,
        {"contains_credentials", "contains_response_payloads", "contains_state_tokens"},
    )
    result = report.get("result")
    clients = report.get("clients")
    if not isinstance(result, dict) or not isinstance(clients, dict):
        raise ValueError("Consumer gate is incomplete")
    expected_clients = {
        "published_jvm_sdk_methods": set(PUBLIC_API_METHODS),
        "trs80_kmp_methods": {
            "downloadState",
            "fetchMediaImages",
            "getApp",
            "listApps",
            "uploadState",
        },
        "trs80_embedded_c_methods": {"fetchMediaImages", "getApp", "listApps"},
    }
    return (
        result.get("passes") is True
        and report.get("safety", {}).get("production_host_rejected") is True
        and report.get("safety", {}).get("synthetic_state_only") is True
        and set(clients) == set(expected_clients)
        and all(set(clients[name]) == methods for name, methods in expected_clients.items())
    )


def _public_transport_passes(report: Mapping[str, Any]) -> bool:
    if (
        report.get("schema_version") != 1
        or report.get("kind") != "retrostore_public_http_https_transport_parity"
    ):
        raise ValueError("Public transport report identity is invalid")
    summary = report.get("summary")
    scope = report.get("scope")
    if not isinstance(summary, dict) or not isinstance(scope, dict):
        raise ValueError("Public transport report is incomplete")
    _require_safety_false(
        report,
        {
            "contains_app_ids_or_filenames",
            "contains_catalog_values",
            "contains_credentials",
            "contains_request_or_response_payloads",
            "production_changed",
        },
    )
    return (
        summary.get("passes") is True
        and summary.get("different") == 0
        and summary.get("matching") == summary.get("total") == 338
        and scope.get("scenario_count") == 338
        and scope.get("api_scenario_count") == 158
        and scope.get("download_scenario_count") == 94
        and scope.get("redirect_scenario_count") == 6
        and scope.get("static_scenario_count") == 79
        and scope.get("public_listing_scenario_count") == 1
    )


def _validate_applied_report(report: Mapping[str, Any], operation: str) -> None:
    if (
        report.get("schema_version") != 1
        or report.get("operation") != operation
        or report.get("applied") is not True
    ):
        raise ValueError(f"{operation} report identity is invalid")


def _require_safety_false(report: Mapping[str, Any], names: set[str]) -> None:
    safety = report.get("safety")
    if not isinstance(safety, dict) or any(safety.get(name) is not False for name in names):
        raise ValueError("Evidence report has unsafe or missing privacy flags")


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


if __name__ == "__main__":
    raise SystemExit(main())

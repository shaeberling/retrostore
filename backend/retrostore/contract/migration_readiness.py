"""Combine sanitized evidence and operator decisions into fail-closed readiness."""

import argparse
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REVISION = "retrostore-api-compat-candidate-redirects1"
_PUBLIC_RESOURCE_DECISIONS = frozenset(
    {
        "candidate_hostnames",
        "go_no_go_owner",
        "rollback_operator",
        "alert_destination",
    }
)
_READ_CANARY_DECISIONS = _PUBLIC_RESOURCE_DECISIONS | {
    "soak_policy",
    "canary_policy",
}


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
        "soak_evidence_is_current": _soak_current(soak),
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
    read_canary_blockers = sorted(pending & _READ_CANARY_DECISIONS)
    if not soak_eligible:
        read_canary_blockers.append("private_zero_diff_soak_not_eligible")
    if not engineering_passes:
        read_canary_blockers.extend(
            f"evidence:{name}" for name, passes in checks.items() if not passes
        )
    retirement_blockers = sorted(pending)
    if not soak_eligible:
        retirement_blockers.append("private_zero_diff_soak_not_eligible")
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
            "soak": {
                "current": soak["soak"]["current"],
                "eligible": soak["soak"]["eligible"],
                "report_count": soak["soak"]["report_count"],
                "required_days": soak["soak"]["required_days"],
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
            "read_canary": {
                "passes": not read_canary_blockers,
                "blockers": sorted(set(read_canary_blockers)),
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
    parser.add_argument("--require-read-canary-ready", action="store_true")
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
    if args.require_read_canary_ready and not report["gates"]["read_canary"]["passes"]:
        return 1
    return 0


def _pending_decisions(decisions: Mapping[str, Any]) -> set[str]:
    if (
        decisions.get("schema_version") != 1
        or decisions.get("status") != "operator_decisions_pending_no_public_authority"
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
    if soak.get("revision") != _REVISION:
        raise ValueError("Soak report revision is not the pinned private candidate")
    value = soak.get("soak")
    if not isinstance(value, dict):
        raise ValueError("Soak report has no status")
    return value.get("current") is True


def _soak_eligible(soak: Mapping[str, Any]) -> bool:
    return _soak_current(soak) and soak["soak"].get("eligible") is True


def _summary_passes(report: Mapping[str, Any], operation: str) -> bool:
    _validate_applied_report(report, operation)
    summary = report.get("summary")
    if not isinstance(summary, dict):
        raise ValueError(f"{operation} has no summary")
    return summary.get("passes") is True and summary.get("failing") == 0


def _consumer_gate_passes(report: Mapping[str, Any]) -> bool:
    _validate_applied_report(report, "deployed_private_consumer_client_gate")
    result = report.get("result")
    clients = report.get("clients")
    if not isinstance(result, dict) or not isinstance(clients, dict):
        raise ValueError("Consumer gate is incomplete")
    return result.get("passes") is True and all(clients.values())


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
    return (
        summary.get("passes") is True
        and summary.get("different") == 0
        and summary.get("matching") == summary.get("total") == 338
        and scope.get("scenario_count") == 338
    )


def _validate_applied_report(report: Mapping[str, Any], operation: str) -> None:
    if (
        report.get("schema_version") != 1
        or report.get("operation") != operation
        or report.get("applied") is not True
    ):
        raise ValueError(f"{operation} report identity is invalid")


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


if __name__ == "__main__":
    raise SystemExit(main())

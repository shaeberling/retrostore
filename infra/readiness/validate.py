#!/usr/bin/env python3
"""Validate the decision register and its candidate-only authority boundary."""

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REGISTER_PATH = Path(__file__).with_name("decision-register.json")
ROUTES_PATH = ROOT / "front-door/route-groups.json"
THRESHOLDS_PATH = ROOT / "front-door/monitoring-thresholds.json"
RETENTION_PATH = ROOT / "data-retention/retention-policy.json"

EXPECTED_PENDING = {
    "alert_destination",
    "migration_backup_retention",
    "public_report_workflow",
    "legacy_user_policy",
}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate(
    register: dict[str, Any],
    routes: dict[str, Any],
    thresholds: dict[str, Any],
    retention: dict[str, Any],
) -> None:
    _require(register.get("schema_version") == 1, "unsupported decision schema")
    _require(
        register.get("status")
        == "candidate_public_resources_approved_no_production_authority",
        "decision register has an unexpected authority boundary",
    )
    pending = register.get("pending")
    _require(isinstance(pending, list), "pending decisions must be a list")
    by_id = {item["id"]: item for item in pending}
    _require(len(by_id) == len(pending), "pending decision IDs must be unique")
    _require(set(by_id) == EXPECTED_PENDING, "pending decision register is incomplete")
    for item in pending:
        _require(
            item["status"] == "confirmation_required",
            f"{item['id']} was changed without updating readiness gates",
        )
        _require(item["required_before"], f"{item['id']} has no blocking scope")

    resolved = register.get("resolved")
    _require(isinstance(resolved, list), "resolved decisions must be a list")
    resolved_ids = {item["id"] for item in resolved}
    _require(len(resolved_ids) == len(resolved), "resolved decision IDs must be unique")
    _require("candidate_hostnames" in resolved_ids, "candidate hostnames were not resolved")
    _require(
        {"go_no_go_owner", "rollback_operator"} <= resolved_ids,
        "cutover owners were not resolved",
    )
    _require(
        "parallel_candidate_resource_creation" in resolved_ids,
        "parallel candidate resource creation was not approved",
    )

    hostnames = routes["hostnames"]
    _require(
        hostnames["parallel_candidate"] == {
            "value": "next.retrostore.org",
            "status": "approved",
        }
        and hostnames["candidate_admin"] == {
            "value": "admin-next.retrostore.org",
            "status": "approved",
        },
        "approved hostname decision differs from route plan",
    )
    ownership = routes["ownership"]
    _require(
        ownership["go_no_go"]["confirmed_owner"] == "Sascha Ha"
        and ownership["go_no_go"]["status"] == "approved"
        and ownership["rollback_operator"]["confirmed_owner"] == "Sascha Ha"
        and ownership["rollback_operator"]["status"] == "approved",
        "owner decision register differs from route plan",
    )
    _require(
        thresholds["status"] == "cutover_policy_approved_monitoring_defaults_provisional",
        "comparison/cutover thresholds were confirmed outside the decision register",
    )
    _require(
        retention["status"] == "proposal_confirmation_required_no_changes",
        "retention policy was confirmed outside the decision register",
    )

    readiness = register["readiness"]
    _require(readiness["private_engineering_may_continue"] is True, "private work blocked")
    _require(readiness["public_resource_creation_ready"] is True, "candidate creation blocked")
    _require(
        readiness["production_traffic_change_ready"] is False
        and readiness["app_engine_retirement_ready"] is False,
        "candidate approval cannot authorize public work: production change or retirement",
    )
    _require(
        register["safety"]
        == {
            "creates_or_changes_resources": False,
            "assigns_unconfirmed_owner": False,
            "selects_alert_recipient": False,
            "authorizes_public_iam_or_dns": True,
            "authorizes_production_cutover": False,
            "authorizes_legacy_data_deletion": False,
        },
        "decision register crossed its candidate-only safety boundary",
    )


def main() -> int:
    validate(
        _load(REGISTER_PATH),
        _load(ROUTES_PATH),
        _load(THRESHOLDS_PATH),
        _load(RETENTION_PATH),
    )
    print("migration decision register and candidate-only authority invariants: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

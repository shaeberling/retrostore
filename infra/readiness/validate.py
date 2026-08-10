#!/usr/bin/env python3
"""Validate the consolidated decision register and its no-authority boundary."""

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REGISTER_PATH = Path(__file__).with_name("decision-register.json")
ROUTES_PATH = ROOT / "front-door/route-groups.json"
THRESHOLDS_PATH = ROOT / "front-door/monitoring-thresholds.json"
RETENTION_PATH = ROOT / "data-retention/retention-policy.json"

EXPECTED_PENDING = {
    "candidate_hostnames",
    "go_no_go_owner",
    "rollback_operator",
    "alert_destination",
    "soak_policy",
    "canary_policy",
    "static_site_policy",
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
        register.get("status") == "operator_decisions_pending_no_public_authority",
        "decision register unexpectedly grants authority",
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

    hostnames = routes["hostnames"]
    _require(
        all(
            hostnames[name]["status"] == "confirmation_required"
            for name in ("front_door_rehearsal", "candidate_api", "candidate_admin")
        ),
        "hostname decision register differs from route plan",
    )
    ownership = routes["ownership"]
    _require(
        ownership["go_no_go"]["confirmed_owner"] is None
        and ownership["rollback_operator"]["confirmed_owner"] is None,
        "owner decision register differs from route plan",
    )
    _require(
        thresholds["status"] == "provisional_defaults_owner_confirmation_required",
        "soak/canary thresholds were confirmed outside the decision register",
    )
    _require(
        retention["status"] == "proposal_confirmation_required_no_changes",
        "retention policy was confirmed outside the decision register",
    )

    readiness = register["readiness"]
    _require(readiness["private_engineering_may_continue"] is True, "private work blocked")
    _require(
        all(
            readiness[name] is False
            for name in (
                "public_resource_creation_ready",
                "production_traffic_change_ready",
                "app_engine_retirement_ready",
            )
        ),
        "pending decisions cannot authorize public work or retirement",
    )
    _require(
        all(value is False for value in register["safety"].values()),
        "decision register unexpectedly authorizes a guarded action",
    )


def main() -> int:
    validate(
        _load(REGISTER_PATH),
        _load(ROUTES_PATH),
        _load(THRESHOLDS_PATH),
        _load(RETENTION_PATH),
    )
    print("migration decision register and no-authority invariants: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

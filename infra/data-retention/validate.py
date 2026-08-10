#!/usr/bin/env python3
"""Validate the proposed no-delete retention boundary without cloud access."""

import json
from pathlib import Path
from typing import Any

POLICY_PATH = Path(__file__).with_name("retention-policy.json")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate(policy: dict[str, Any]) -> None:
    _require(policy.get("schema_version") == 1, "unsupported retention schema")
    _require(
        policy.get("status") == "proposal_confirmation_required_no_changes",
        "retention proposal must remain unapproved",
    )
    observed = policy["observed_cloud_state"]
    comparisons = observed["comparison_reports"]
    _require(
        comparisons["bucket"] == "trs-80-retrostore-assets"
        and comparisons["prefix"] == "operations/comparisons/"
        and comparisons["delete_age_days"] == 90,
        "observed comparison-report lifecycle changed",
    )
    state = observed["synthetic_and_future_state_payloads"]
    _require(
        state["bucket"] == "trs-80-retrostore-state"
        and state["delete_age_days"] == 8
        and state["retention_decision_scope"] == "separate_ephemeral_state_policy",
        "ephemeral state lifecycle was mixed with backup retention",
    )
    _require(
        observed["normalized_migration_exports"]["cloud_backup_location_assigned"]
        is False,
        "backup storage was assigned without approval",
    )

    proposed = policy["proposed_policy"]
    for name in (
        "normalized_catalog_exports",
        "legacy_data_backups",
        "sensitive_identity_reconciliation",
        "orphan_blob_key_mapping",
    ):
        item = proposed[name]
        retention_fields = [
            value for key, value in item.items() if key.startswith("retain_days_after_")
        ]
        _require(
            len(retention_fields) == 1
            and isinstance(retention_fields[0], int)
            and retention_fields[0] >= 90,
            f"{name} has an unsafe proposed retention window",
        )
        _require(
            item["automatic_deletion_enabled"] is False
            and item["deletion_mode"] == "manual_review_after_retention_window",
            f"{name} must not enable automatic deletion",
        )
    report_queue = proposed["public_report_queue"]
    _require(
        report_queue["retention_days"] is None
        and report_queue["status"]
        == "not_applicable_until_queue_email_or_retire_decision",
        "report retention was inferred before the report workflow decision",
    )

    blockers = set(policy["deletion_blockers"])
    _require(
        {
            "app_engine_still_serves_any_migrating_route",
            "state_or_catalog_rollback_window_open",
            "retention_policy_unapproved",
            "legal_or_operational_hold",
        }.issubset(blockers),
        "required deletion blockers are missing",
    )
    approvals = policy["required_approvals"]
    _require(
        approvals == {
            "data_owner": None,
            "rollback_owner": None,
            "status": "confirmation_required",
        },
        "retention owners were assigned without confirmation",
    )
    safety = policy["safety"]
    _require(
        all(value is False for value in safety.values()),
        "retention proposal unexpectedly claims a mutation or cloud action",
    )


def main() -> int:
    policy = json.loads(POLICY_PATH.read_text())
    if not isinstance(policy, dict):
        raise ValueError("retention policy must be a JSON object")
    validate(policy)
    print("data-retention proposal and no-delete invariants: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

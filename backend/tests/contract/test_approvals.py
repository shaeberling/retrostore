import json
from datetime import date
from pathlib import Path

import pytest

from retrostore.contract.approvals import (
    DifferenceApproval,
    difference_fingerprint,
    evaluate_approvals,
    load_approvals,
)

TODAY = date(2026, 8, 6)


def _report(difference: object | None = None) -> dict[str, object]:
    return {
        "results": [
            {
                "scenario": "catalog",
                "differences": {} if difference is None else {"semantic_body": difference},
            }
        ]
    }


def _approval(difference: object, expires_on: date = date(2026, 8, 7)) -> DifferenceApproval:
    return DifferenceApproval(
        scenario="catalog",
        field="semantic_body",
        difference_sha256=difference_fingerprint("catalog", "semantic_body", difference),
        reason="Reviewed transitional URL only",
        owner="migration-owner@example.test",
        expires_on=expires_on,
    )


def test_exact_unexpired_approval_passes_and_is_attributed() -> None:
    difference = {"expected": "old", "actual": "new"}

    report = evaluate_approvals(_report(difference), (_approval(difference),), today=TODAY)

    assert report["approval_gate"] == {
        "evaluated_on": "2026-08-06",
        "passes": True,
        "difference_fields": 1,
        "approved": 1,
        "unapproved": 0,
        "expired_approvals": 0,
        "stale_approvals": 0,
    }
    status = report["results"][0]["difference_approvals"]["semantic_body"]
    assert status["status"] == "approved"
    assert status["owner"] == "migration-owner@example.test"


def test_zero_differences_with_no_approvals_passes() -> None:
    report = evaluate_approvals(_report(), today=TODAY)

    assert report["approval_gate"] == {
        "evaluated_on": "2026-08-06",
        "passes": True,
        "difference_fields": 0,
        "approved": 0,
        "unapproved": 0,
        "expired_approvals": 0,
        "stale_approvals": 0,
    }


def test_changed_difference_does_not_match_and_makes_approval_stale() -> None:
    approved_difference = {"expected": "old", "actual": "reviewed"}
    current_difference = {"expected": "old", "actual": "changed again"}

    report = evaluate_approvals(
        _report(current_difference),
        (_approval(approved_difference),),
        today=TODAY,
    )

    assert report["approval_gate"]["passes"] is False
    assert report["approval_gate"]["unapproved"] == 1
    assert report["approval_gate"]["stale_approvals"] == 1


def test_expired_or_unused_approval_fails_gate() -> None:
    difference = {"expected": 1, "actual": 2}
    expired = _approval(difference, date(2026, 8, 5))
    expired_report = evaluate_approvals(_report(difference), (expired,), today=TODAY)
    unused_report = evaluate_approvals(_report(), (_approval(difference),), today=TODAY)

    assert expired_report["approval_gate"]["expired_approvals"] == 1
    assert expired_report["approval_gate"]["unapproved"] == 1
    assert expired_report["approval_gate"]["passes"] is False
    assert unused_report["approval_gate"]["stale_approvals"] == 1
    assert unused_report["approval_gate"]["passes"] is False


def test_load_approvals_rejects_duplicate_scenario_fields(tmp_path: Path) -> None:
    difference = {"expected": 1, "actual": 2}
    entry = {
        "scenario": "catalog",
        "field": "semantic_body",
        "difference_sha256": difference_fingerprint("catalog", "semantic_body", difference),
        "reason": "Reviewed",
        "owner": "owner@example.test",
        "expires_on": "2026-08-07",
    }
    path = tmp_path / "approvals.json"
    path.write_text(json.dumps({"schema_version": 1, "approvals": [entry, entry]}))

    with pytest.raises(ValueError, match="duplicate"):
        load_approvals(path)


def test_load_approvals_rejects_non_object_entry(tmp_path: Path) -> None:
    path = tmp_path / "approvals.json"
    path.write_text(json.dumps({"schema_version": 1, "approvals": ["invalid"]}))

    with pytest.raises(ValueError, match="JSON object"):
        load_approvals(path)

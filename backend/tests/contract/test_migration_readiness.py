import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from retrostore.contract.migration_readiness import evaluate_migration_readiness

DECISIONS_PATH = Path(__file__).parents[3] / "infra/readiness/decision-register.json"


def _decisions() -> dict[str, object]:
    return json.loads(DECISIONS_PATH.read_text())


def _soak(*, eligible: bool = False) -> dict[str, object]:
    return {
        "schema_version": 1,
        "operation": "private_api_zero_diff_soak_status",
        "applied": True,
        "revision": "retrostore-api-compat-candidate-redirects1",
        "soak": {
            "current": True,
            "eligible": eligible,
            "report_count": 3 if eligible else 2,
            "required_reports": 3,
            "started_at": "2026-08-10T03:55:01+00:00",
            "latest_at": "2026-08-10T04:18:28+00:00",
            "reasons": [] if eligible else ["required_report_count_not_reached"],
        },
        "safety": {
            "contains_catalog_field_values": False,
            "contains_comparison_results": False,
            "contains_credentials": False,
            "contains_request_or_response_payloads": False,
            "contains_state_tokens": False,
        },
    }


def _summary_report(operation: str, *, passes: bool = True) -> dict[str, object]:
    candidate = operation == "private_cloud_run_candidate_drift_audit"
    return {
        "schema_version": 1,
        "operation": operation,
        "applied": True,
        "summary": {
            "passes": passes,
            "failing": 0 if passes else 1,
            "passing": (3 if candidate else 9) - (not passes),
            "service_count" if candidate else "check_count": 3 if candidate else 9,
        },
        "safety": (
            {
                "contains_credentials": False,
                "contains_environment_values": False,
                "contains_invoker_member_values": False,
                "production_routing_changed": False,
                "public_iam_changed": False,
            }
            if candidate
            else {
                "contains_comparison_payloads": False,
                "contains_credentials": False,
                "contains_environment_values": False,
                "contains_iam_member_values": False,
                "production_routing_changed": False,
            }
        ),
    }


def _consumers(*, passes: bool = True) -> dict[str, object]:
    return {
        "schema_version": 1,
        "operation": "deployed_private_consumer_client_gate",
        "applied": True,
        "result": {"passes": passes},
        "clients": {
            "published_jvm_sdk_methods": [
                "downloadState",
                "downloadStateMemoryRegion",
                "fetchMediaImageRefs",
                "fetchMediaImageRegion",
                "fetchMediaImages",
                "getApp",
                "listApps",
                "listAppsNano",
                "uploadState",
            ],
            "trs80_kmp_methods": [
                "downloadState",
                "fetchMediaImages",
                "getApp",
                "listApps",
                "uploadState",
            ],
            "trs80_embedded_c_methods": ["fetchMediaImages", "getApp", "listApps"],
        },
        "safety": {
            "contains_credentials": False,
            "contains_response_payloads": False,
            "contains_state_tokens": False,
            "production_host_rejected": True,
            "synthetic_state_only": True,
        },
    }


def _transport(*, passes: bool = True) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "retrostore_public_http_https_transport_parity",
        "scope": {
            "scenario_count": 338,
            "api_scenario_count": 158,
            "download_scenario_count": 94,
            "redirect_scenario_count": 6,
            "static_scenario_count": 79,
            "public_listing_scenario_count": 1,
        },
        "summary": {
            "total": 338,
            "matching": 338 if passes else 337,
            "different": 0 if passes else 1,
            "passes": passes,
        },
        "safety": {
            "contains_app_ids_or_filenames": False,
            "contains_catalog_values": False,
            "contains_credentials": False,
            "contains_request_or_response_payloads": False,
            "production_changed": False,
        },
    }


def _evaluate(**overrides) -> dict[str, object]:
    inputs = {
        "decisions": _decisions(),
        "soak": _soak(),
        "candidates": _summary_report("private_cloud_run_candidate_drift_audit"),
        "comparator": _summary_report("scheduled_comparator_runtime_drift_audit"),
        "consumers": _consumers(),
        "public_transport": _transport(),
        "generated_at": datetime(2026, 8, 10, tzinfo=UTC),
    }
    inputs.update(overrides)
    return evaluate_migration_readiness(**inputs)


def test_readiness_distinguishes_passing_evidence_from_pending_authority() -> None:
    report = _evaluate()

    assert report["evidence"]["passes"] is True
    assert report["gates"]["private_engineering_evidence"] == {
        "passes": True,
        "blockers": [],
    }
    assert report["decisions"]["pending_count"] == 4
    assert report["gates"]["public_resource_creation"]["passes"] is True
    assert report["gates"]["production_cutover"]["passes"] is False
    assert "private_zero_diff_evidence_not_ready" in report["gates"]["production_cutover"][
        "blockers"
    ]
    assert report["gates"]["app_engine_retirement"]["passes"] is False
    assert report["safety"]["mutation_or_cutover_capability_present"] is False


def test_readiness_reports_failed_real_client_evidence() -> None:
    report = _evaluate(consumers=_consumers(passes=False))

    assert report["evidence"]["passes"] is False
    assert "pinned_consumers_pass" in report["gates"]["private_engineering_evidence"][
        "blockers"
    ]
    assert "evidence:pinned_consumers_pass" in report["gates"]["production_cutover"][
        "blockers"
    ]


def test_readiness_rejects_evidence_for_a_different_revision() -> None:
    soak = _soak()
    soak["revision"] = "retrostore-api-compat-candidate-other"

    with pytest.raises(ValueError, match="not the pinned private candidate"):
        _evaluate(soak=soak)


def test_three_report_streak_removes_only_the_evidence_blocker() -> None:
    report = _evaluate(soak=_soak(eligible=True))

    assert "private_zero_diff_evidence_not_ready" not in report["gates"]["production_cutover"][
        "blockers"
    ]
    assert report["gates"]["production_cutover"]["passes"] is False
    assert "alert_destination" in report["gates"]["production_cutover"]["blockers"]


def test_readiness_rejects_green_evidence_with_unsafe_privacy_flags() -> None:
    transport = _transport()
    transport["safety"]["contains_catalog_values"] = True

    with pytest.raises(ValueError, match="unsafe or missing privacy flags"):
        _evaluate(public_transport=transport)

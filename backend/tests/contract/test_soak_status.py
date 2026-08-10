import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import retrostore.contract.soak_status as soak_status
from retrostore.contract.soak_status import ComparisonEvidence

_REVISION = "retrostore-api-compat-candidate-observability2"


def _thresholds(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "comparison": {
                    "schedule_seconds": 3600,
                    "continuous_zero_diff_soak_days": 14,
                    "maximum_unexplained_differences": 0,
                    "maximum_unapproved_differences": 0,
                    "material_fix_restarts_soak": True,
                },
            }
        )
    )
    return path


def _baseline(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "private_evidence_only_no_cutover_authority",
                "project": "trs-80",
                "region": "us-central1",
                "service": "retrostore-api-compat-candidate",
                "candidate_url": (
                    "https://retrostore-api-compat-candidate-760396810462."
                    "us-central1.run.app"
                ),
                "revision": _REVISION,
                "revision_ready_at": "2026-08-10T00:39:20Z",
                "soak_not_before": "2026-08-10T00:40:00Z",
                "production_routing_changed": False,
                "catalog_activation_authorized": False,
                "load_balancer_authorized": False,
            }
        )
    )
    return path


def _arguments(tmp_path: Path) -> list[str]:
    return [
        "--thresholds",
        str(_thresholds(tmp_path / "thresholds.json")),
        "--baseline",
        str(_baseline(tmp_path / "baseline.json")),
        "--output",
        str(tmp_path / "status.json"),
    ]


def _artifact(
    generated_at: datetime,
    *,
    different: bool = False,
    schema_version: int = 2,
) -> tuple[str, bytes]:
    results = [
        {
            "scenario": f"scenario-{index}",
            "differences": {"body": {"changed": True}} if different and index == 0 else {},
        }
        for index in range(158)
    ]
    report = {
        "schema_version": 1,
        "reference_url": "https://retrostore.org",
        "candidate_url": (
            "https://retrostore-api-compat-candidate-760396810462.us-central1.run.app"
        ),
        "summary": {
            "total": 158,
            "matching": 157 if different else 158,
            "different": 1 if different else 0,
        },
        "scope": {"scenario_count": 158},
        "results": results,
        "approval_gate": {
            "passes": not different,
            "difference_fields": 1 if different else 0,
            "unapproved": 1 if different else 0,
            "expired_approvals": 0,
            "stale_approvals": 0,
        },
    }
    artifact = {
        "schema_version": schema_version,
        "generated_at": generated_at.isoformat(),
        "kind": (
            "retrostore_exhaustive_http_comparison"
            if schema_version == 1
            else "retrostore_multi_surface_http_comparison"
        ),
        "report": report,
    }
    if schema_version == 2:
        artifact["surface_reports"] = {
            "legacy_downloads": {
                "schema_version": 1,
                "kind": "retrostore_legacy_download_comparison",
                "reference_url": "https://retrostore.org",
                "candidate": (
                    "https://retrostore-api-compat-candidate-760396810462."
                    "us-central1.run.app"
                ),
                "scope": {"scenario_count": 94},
                "summary": {
                    "total": 94,
                    "matching": 94,
                    "different": 0,
                    "passes": True,
                },
                "differences": [],
            },
            "public_app_list": {
                "schema_version": 1,
                "kind": "retrostore_public_website_app_list_comparison",
                "reference_url": "https://retrostore.org",
                "candidate": (
                    "https://retrostore-api-compat-candidate-760396810462."
                    "us-central1.run.app"
                ),
                "scope": {
                    "reference_app_count": 32,
                    "candidate_app_count": 32,
                },
                "summary": {"different": 0, "passes": True},
                "differences": [],
            },
        }
        artifact["overall_gate"] = {
            "passes": not different,
            "api_contract_passes": not different,
            "legacy_downloads_passes": True,
            "public_app_list_passes": True,
        }
    body = (
        json.dumps(
            artifact,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode()
    digest = hashlib.sha256(body).hexdigest()
    name = (
        f"operations/comparisons/{generated_at:%Y/%m/%d}/"
        f"{generated_at:%Y%m%dT%H%M%S%fZ}-{digest[:16]}.json"
    )
    return name, body


def _evidence(at: datetime, *, passes: bool = True) -> ComparisonEvidence:
    return ComparisonEvidence(
        generated_at=at,
        object_name=f"report-{at.isoformat()}",
        sha256="a" * 64,
        total=158,
        matching=158 if passes else 157,
        different=0 if passes else 1,
        difference_fields=0 if passes else 1,
        approval_gate_passes=passes,
        additional_surfaces_pass=passes,
    )


def test_dry_run_has_no_cloud_access(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        soak_status,
        "_require_gcloud_project",
        lambda: pytest.fail("dry run accessed gcloud"),
    )

    assert soak_status.main(_arguments(tmp_path)) == 0

    report = json.loads((tmp_path / "status.json").read_text())
    assert report["applied"] is False
    assert report["policy"] == {"required_days": 14, "schedule_seconds": 3600}


def test_apply_requires_exact_confirmations_before_cloud_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        soak_status,
        "_require_gcloud_project",
        lambda: pytest.fail("invalid confirmation accessed gcloud"),
    )

    with pytest.raises(ValueError, match="confirm-project"):
        soak_status.main([*_arguments(tmp_path), "--apply"])


def test_parser_validates_digest_counts_and_zero_diff_gate() -> None:
    generated_at = datetime(2026, 8, 10, 1, 17, 1, 123456, tzinfo=UTC)
    name, body = _artifact(generated_at)

    evidence = soak_status.parse_comparison_artifact(name, body)

    assert evidence.generated_at == generated_at
    assert evidence.zero_diff_passes is True
    assert evidence.additional_surfaces_pass is True
    with pytest.raises(ValueError, match="digest"):
        soak_status.parse_comparison_artifact(name, body + b" ")


def test_legacy_api_only_artifact_no_longer_satisfies_multi_surface_soak() -> None:
    generated_at = datetime(2026, 8, 10, 1, 17, 1, 123456, tzinfo=UTC)
    name, body = _artifact(generated_at, schema_version=1)

    evidence = soak_status.parse_comparison_artifact(name, body)

    assert evidence.approval_gate_passes is True
    assert evidence.additional_surfaces_pass is False
    assert evidence.zero_diff_passes is False


def test_soak_streak_restarts_after_failure_and_rejects_staleness() -> None:
    start = datetime(2026, 8, 10, tzinfo=UTC)
    evidence = [
        _evidence(start + timedelta(hours=hour), passes=hour != 2)
        for hour in range(5)
    ]

    current = soak_status.evaluate_soak(
        evidence,
        not_before=start,
        as_of=start + timedelta(hours=4, minutes=30),
        schedule_seconds=3600,
        required_days=14,
    )
    stale = soak_status.evaluate_soak(
        evidence,
        not_before=start,
        as_of=start + timedelta(hours=6),
        schedule_seconds=3600,
        required_days=14,
    )

    assert current["current"] is True
    assert current["report_count"] == 2
    assert current["started_at"] == (start + timedelta(hours=3)).isoformat()
    assert current["eligible"] is False
    assert stale["current"] is False
    assert stale["reasons"] == ["latest_report_is_stale"]


def test_soak_streak_breaks_on_gap_and_becomes_eligible_after_fourteen_days() -> None:
    start = datetime(2026, 8, 1, tzinfo=UTC)
    recent = [_evidence(start + timedelta(hours=hour)) for hour in range(14 * 24 + 1)]
    old = _evidence(start - timedelta(hours=3))

    report = soak_status.evaluate_soak(
        [old, *recent],
        not_before=start - timedelta(hours=4),
        as_of=start + timedelta(days=14),
        schedule_seconds=3600,
        required_days=14,
    )

    assert report["current"] is True
    assert report["eligible"] is True
    assert report["report_count"] == 337
    assert report["started_at"] == start.isoformat()
    assert report["maximum_observed_gap_seconds"] == 3600

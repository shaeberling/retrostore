import json
from argparse import Namespace
from pathlib import Path

import pytest

import retrostore.contract.cloud_run_metrics as metrics

_REVISION = "retrostore-api-compat-candidate-observability2"


def _load_report(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "operation": "private_api_read_load_test",
                "applied": True,
                "read_only": True,
                "started_at": "2026-08-10T01:24:14+00:00",
                "generated_at": "2026-08-10T01:25:09+00:00",
                "candidate_url": (
                    "https://retrostore-api-compat-candidate-760396810462.us-central1.run.app"
                ),
                "gate": {"passes": True},
            }
        )
    )
    return path


def _arguments(tmp_path: Path) -> list[str]:
    return [
        "--load-report",
        str(_load_report(tmp_path / "load.json")),
        "--revision",
        _REVISION,
        "--output",
        str(tmp_path / "metrics.json"),
    ]


def test_dry_run_does_not_authenticate_or_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        metrics,
        "_gcloud_access_token",
        lambda: pytest.fail("dry run authenticated"),
    )

    assert metrics.main(_arguments(tmp_path)) == 0

    report = json.loads((tmp_path / "metrics.json").read_text())
    assert report["applied"] is False
    assert report["read_only"] is True
    assert report["project"] == "trs-80"
    assert report["interval"]["margin_seconds"] == 180


def test_apply_requires_all_exact_confirmations_before_authentication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        metrics,
        "_require_gcloud_project",
        lambda: pytest.fail("invalid confirmation checked gcloud"),
    )

    with pytest.raises(ValueError, match="confirm-project"):
        metrics.main([*_arguments(tmp_path), "--apply"])


def test_summarizes_numeric_and_distribution_points() -> None:
    report = metrics._summarize_time_series(
        [
            {
                "metric": {"labels": {"state": "active"}},
                "points": [
                    {
                        "interval": {"endTime": "2026-08-10T01:25:00Z"},
                        "value": {"int64Value": "2"},
                    }
                ],
            },
            {
                "metric": {"labels": {}},
                "points": [
                    {
                        "interval": {"endTime": "2026-08-10T01:26:00Z"},
                        "value": {
                            "distributionValue": {
                                "count": "4",
                                "mean": 0.25,
                                "range": {"min": 0.1, "max": 0.4},
                            }
                        },
                    },
                    {
                        "interval": {"endTime": "2026-08-10T01:27:00Z"},
                        "value": {
                            "distributionValue": {
                                "count": "2",
                                "mean": 0.5,
                                "range": {"min": 0.3, "max": 0.7},
                            }
                        },
                    },
                ],
            },
        ]
    )

    assert report["series_count"] == 2
    assert report["point_count"] == 3
    assert report["numeric"]["maximum"] == 2
    assert report["distribution"]["observation_count"] == 6
    assert report["distribution"]["weighted_mean"] == pytest.approx(1 / 3)
    assert report["distribution"]["observed_maximum"] == 0.7


def test_validate_rejects_non_candidate_revision() -> None:
    args = Namespace(revision="production", margin_seconds=180)
    report = {
        "operation": "private_api_read_load_test",
        "applied": True,
        "read_only": True,
        "started_at": "2026-08-10T01:24:14+00:00",
        "generated_at": "2026-08-10T01:25:09+00:00",
        "candidate_url": (
            "https://retrostore-api-compat-candidate-760396810462.us-central1.run.app"
        ),
        "gate": {"passes": True},
    }

    with pytest.raises(ValueError, match="Revision must belong"):
        metrics._validate_inputs(args, report)

import json
from argparse import Namespace
from pathlib import Path

import pytest

import retrostore.contract.cloud_run_metrics as metrics

_REVISION = "retrostore-api-compat-candidate-observability2"


def _load_report(path: Path, *, gate_passes: bool = True) -> Path:
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
                "gate": {"passes": gate_passes},
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


def test_failed_load_gate_remains_valid_resource_evidence(tmp_path: Path) -> None:
    args = Namespace(revision=_REVISION, margin_seconds=180)
    report = json.loads(_load_report(tmp_path / "failed.json", gate_passes=False).read_text())

    start, end = metrics._validate_inputs(args, report)

    assert end > start


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


def test_summarizes_distribution_histogram_percentile_bounds() -> None:
    report = metrics._summarize_time_series(
        [
            {
                "metric": {"labels": {}},
                "points": [
                    {
                        "interval": {"endTime": "2026-08-10T01:26:00Z"},
                        "value": {
                            "distributionValue": {
                                "count": "100",
                                "mean": 12.0,
                                "bucketOptions": {"explicitBuckets": {"bounds": [10, 20, 30]}},
                                "bucketCounts": [40, 55, 4, 1],
                            }
                        },
                    }
                ],
            }
        ]
    )

    histogram = report["distribution"]["histogram"]
    assert histogram["bucket_observation_count"] == 100
    assert histogram["approximate_p50_upper_bound"] == 20
    assert histogram["approximate_p95_upper_bound"] == 20
    assert histogram["approximate_p99_upper_bound"] == 30


def test_histogram_aggregation_accepts_omitted_trailing_zero_buckets() -> None:
    options = {"explicitBuckets": {"bounds": [10, 20, 30]}}
    report = metrics._summarize_time_series(
        [
            {
                "metric": {"labels": {}},
                "points": [
                    {
                        "value": {
                            "distributionValue": {
                                "count": "2",
                                "mean": 5,
                                "bucketOptions": options,
                                "bucketCounts": [2],
                            }
                        }
                    },
                    {
                        "value": {
                            "distributionValue": {
                                "count": "2",
                                "mean": 25,
                                "bucketOptions": options,
                                "bucketCounts": [0, 0, 2],
                            }
                        }
                    },
                ],
            }
        ]
    )

    histogram = report["distribution"]["histogram"]
    assert histogram["bucket_options_consistent"] is True
    assert histogram["bucket_observation_count"] == 4
    assert histogram["approximate_p50_upper_bound"] == 10
    assert histogram["approximate_p95_upper_bound"] == 30


def test_linear_histogram_uses_protobuf_default_offset() -> None:
    assert metrics._histogram_bucket_upper_bound(
        {"linearBuckets": {"numFiniteBuckets": 10, "width": 0.1}}, 3
    ) == pytest.approx(0.3)


def test_resource_evidence_gate_detects_delayed_monitoring_samples() -> None:
    report = {
        "summary": {"request_count": 100},
        "configuration": {"warmup_requests": 10},
    }
    observed = {
        "billable_instance_time": {"numeric": {"count": 1}},
        "cpu_allocation_time": {"numeric": {"count": 1}},
        "request_count": {"numeric": {"sum": 109}},
        "request_latency": {"distribution": {"observation_count": 50}},
        "cpu_utilization": {"distribution": {"observation_count": 1}},
        "instance_count": {"numeric": {"count": 1}},
        "max_request_concurrency": {"distribution": {"observation_count": 1}},
        "memory_allocation_time": {"numeric": {"count": 1}},
        "memory_utilization": {"distribution": {"observation_count": 1}},
    }

    gate = metrics._resource_evidence_gate(observed, report)

    assert gate["passes"] is False
    assert gate["expected_minimum_request_count"] == 110
    assert gate["reasons"] == ["native_request_volume_is_incomplete"]
    assert gate["warnings"] == [
        "native_request_count_is_lower_than_expected",
        "native_request_latency_count_is_lower_than_expected",
    ]


def test_complete_latency_histogram_can_corroborate_request_volume() -> None:
    report = {
        "summary": {"request_count": 100},
        "configuration": {"warmup_requests": 10},
    }
    observed = {
        "billable_instance_time": {"numeric": {"count": 1}},
        "cpu_allocation_time": {"numeric": {"count": 1}},
        "request_count": {"numeric": {"sum": 109}},
        "request_latency": {"distribution": {"observation_count": 110}},
        "cpu_utilization": {"distribution": {"observation_count": 1}},
        "instance_count": {"numeric": {"count": 1}},
        "max_request_concurrency": {"distribution": {"observation_count": 1}},
        "memory_allocation_time": {"numeric": {"count": 1}},
        "memory_utilization": {"distribution": {"observation_count": 1}},
    }

    gate = metrics._resource_evidence_gate(observed, report)

    assert gate["passes"] is True
    assert gate["reasons"] == []
    assert gate["warnings"] == ["native_request_count_is_lower_than_expected"]


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

import hashlib
import json
from pathlib import Path

import pytest

import retrostore.contract.capacity_summary as capacity_summary


def _reports(tmp_path: Path, concurrency: int, *, passes: bool = True) -> tuple[Path, Path]:
    load_path = tmp_path / f"load-{concurrency}.json"
    metrics_path = tmp_path / f"metrics-{concurrency}.json"
    load = {
        "schema_version": 1,
        "operation": "private_api_read_load_test",
        "applied": True,
        "read_only": True,
        "candidate_url": (
            "https://retrostore-api-compat-candidate-760396810462.us-central1.run.app"
        ),
        "configuration": {
            "concurrency": concurrency,
            "actual_elapsed_seconds": 10.0,
            "warmup_requests": 2,
        },
        "summary": {
            "request_count": 100,
            "requests_per_second": 10.0,
            "response_bytes": 1000,
            "transport_error_count": 0,
            "contract_mismatch_count": 0,
            "server_error_count": 0,
        },
        "gate": {"passes": passes},
        "performance": {
            "methods": {"getApp": {"passes": passes}},
        },
    }
    load_bytes = (json.dumps(load, sort_keys=True) + "\n").encode()
    load_path.write_bytes(load_bytes)
    distribution = {
        "observation_count": 1,
        "weighted_mean": 0.25,
        "histogram": {
            "approximate_p95_upper_bound": 0.5,
            "approximate_p99_upper_bound": 0.75,
        },
    }
    metrics = {
        "schema_version": 1,
        "operation": "private_api_cloud_run_metrics",
        "applied": True,
        "read_only": True,
        "service": "retrostore-api-compat-candidate",
        "revision": "retrostore-api-compat-candidate-observability2",
        "source_load_report_sha256": hashlib.sha256(load_bytes).hexdigest(),
        "evidence_gate": {"passes": True, "warnings": []},
        "metrics": {
            "billable_instance_time": {"numeric": {"sum": 10}},
            "cpu_allocation_time": {"numeric": {"sum": 10}},
            "cpu_utilization": {"distribution": distribution},
            "memory_utilization": {"distribution": distribution},
            "request_latency": {"distribution": distribution},
            "max_request_concurrency": {"distribution": distribution},
            "memory_allocation_time": {"numeric": {"sum": 5}},
            "instance_count": {"numeric": {"maximum": 1}},
            "startup_latency": {"distribution": distribution},
        },
    }
    metrics_path.write_text(json.dumps(metrics, sort_keys=True) + "\n")
    return load_path, metrics_path


def test_summarizes_passing_step_and_nonpassing_boundary(tmp_path: Path) -> None:
    passing = _reports(tmp_path, 12)
    failing = _reports(tmp_path, 20, passes=False)
    output = tmp_path / "summary.json"

    assert (
        capacity_summary.main(
            [
                "--pair",
                *(str(path) for path in failing),
                "--pair",
                *(str(path) for path in passing),
                "--output",
                str(output),
                "--require-integrity",
            ]
        )
        == 0
    )

    report = json.loads(output.read_text())
    assert report["summary"]["contract_integrity_passes"] is True
    assert report["summary"]["highest_passing_concurrency"] == 12
    assert report["summary"]["first_nonpassing_concurrency"] == 20
    assert report["summary"]["total_billable_instance_seconds"] == 20
    assert report["summary"]["total_memory_allocation_gibibyte_seconds"] == 10
    assert report["steps"][1]["failed_latency_methods"] == ["getApp"]
    assert report["safety"]["contains_request_or_response_payloads"] is False


def test_rejects_metrics_not_bound_to_load_report(tmp_path: Path) -> None:
    load, metrics = _reports(tmp_path, 8)
    value = json.loads(metrics.read_text())
    value["source_load_report_sha256"] = "0" * 64
    metrics.write_text(json.dumps(value))

    with pytest.raises(ValueError, match="not bound"):
        capacity_summary.main(
            ["--pair", str(load), str(metrics), "--output", str(tmp_path / "out.json")]
        )

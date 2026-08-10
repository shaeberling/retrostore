"""Combine guarded load steps and native metrics into a privacy-safe capacity summary."""

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_CANDIDATE_URL = (
    "https://retrostore-api-compat-candidate-760396810462.us-central1.run.app"
)
_SERVICE = "retrostore-api-compat-candidate"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pair",
        nargs=2,
        action="append",
        metavar=("LOAD_REPORT", "METRICS_REPORT"),
        required=True,
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-integrity", action="store_true")
    args = parser.parse_args(argv)

    steps = tuple(
        _load_step(Path(load_path), Path(metrics_path))
        for load_path, metrics_path in args.pair
    )
    concurrencies = [step["configuration"]["concurrency"] for step in steps]
    if len(set(concurrencies)) != len(concurrencies):
        raise ValueError("Capacity summary contains duplicate concurrency steps")
    ordered = sorted(steps, key=lambda step: step["configuration"]["concurrency"])
    revisions = {step["revision"] for step in ordered}
    if len(revisions) != 1:
        raise ValueError("Capacity summary steps must use one exact revision")
    integrity_passes = all(step["contract_integrity_passes"] for step in ordered)
    passing = [step for step in ordered if step["load_gate_passes"]]
    failing = [step for step in ordered if not step["load_gate_passes"]]
    report = {
        "schema_version": 1,
        "operation": "private_api_capacity_summary",
        "generated_at": datetime.now(UTC).isoformat(),
        "read_only": True,
        "service": _SERVICE,
        "revision": next(iter(revisions)),
        "steps": ordered,
        "summary": {
            "step_count": len(ordered),
            "total_measured_requests": sum(
                step["result"]["request_count"] for step in ordered
            ),
            "total_response_bytes": sum(
                step["result"]["response_bytes"] for step in ordered
            ),
            "total_billable_instance_seconds": sum(
                step["native_metrics"]["billable_instance_seconds"] for step in ordered
            ),
            "total_cpu_allocation_seconds": sum(
                step["native_metrics"]["cpu_allocation_seconds"] for step in ordered
            ),
            "total_memory_allocation_gibibyte_seconds": sum(
                step["native_metrics"]["memory_allocation_gibibyte_seconds"]
                for step in ordered
            ),
            "contract_integrity_passes": integrity_passes,
            "highest_passing_concurrency": (
                max(step["configuration"]["concurrency"] for step in passing)
                if passing
                else None
            ),
            "first_nonpassing_concurrency": (
                min(step["configuration"]["concurrency"] for step in failing)
                if failing
                else None
            ),
            "highest_passing_requests_per_second": (
                max(step["result"]["requests_per_second"] for step in passing)
                if passing
                else None
            ),
        },
        "interpretation": {
            "provisional_front_door_latency_gate": True,
            "a_nonpassing_step_is_preserved": bool(failing),
            "does_not_change_cloud_run_configuration": True,
            "does_not_authorize_production_traffic": True,
        },
        "safety": {
            "contains_request_or_response_payloads": False,
            "contains_catalog_field_values": False,
            "contains_credentials": False,
            "contains_state_tokens": False,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report["summary"], sort_keys=True, separators=(",", ":")))
    if args.require_integrity and not integrity_passes:
        return 1
    return 0


def _load_step(load_path: Path, metrics_path: Path) -> dict[str, Any]:
    load_bytes = load_path.read_bytes()
    load = json.loads(load_bytes)
    metrics = json.loads(metrics_path.read_bytes())
    if (
        load.get("schema_version") != 1
        or load.get("operation") != "private_api_read_load_test"
        or load.get("applied") is not True
        or load.get("read_only") is not True
        or load.get("candidate_url") != _CANDIDATE_URL
    ):
        raise ValueError(f"Invalid private load report: {load_path}")
    if (
        metrics.get("schema_version") != 1
        or metrics.get("operation") != "private_api_cloud_run_metrics"
        or metrics.get("applied") is not True
        or metrics.get("read_only") is not True
        or metrics.get("service") != _SERVICE
        or metrics.get("source_load_report_sha256") != hashlib.sha256(load_bytes).hexdigest()
    ):
        raise ValueError(f"Metrics report is not bound to its load report: {metrics_path}")
    if metrics.get("evidence_gate", {}).get("passes") is not True:
        raise ValueError(f"Metrics evidence is incomplete: {metrics_path}")

    configuration = load.get("configuration", {})
    summary = load.get("summary", {})
    load_gate = load.get("gate", {})
    if not isinstance(load_gate.get("passes"), bool):
        raise ValueError(f"Load report has no completed gate: {load_path}")
    integer_fields = (
        summary.get("request_count"),
        summary.get("response_bytes"),
        summary.get("transport_error_count"),
        summary.get("contract_mismatch_count"),
        summary.get("server_error_count"),
        configuration.get("concurrency"),
    )
    if any(isinstance(value, bool) or not isinstance(value, int) for value in integer_fields):
        raise ValueError(f"Load report has invalid aggregate counts: {load_path}")
    failed_methods = sorted(
        name
        for name, value in load.get("performance", {}).get("methods", {}).items()
        if value.get("passes") is not True
    )
    metric_values = metrics["metrics"]
    return {
        "revision": metrics["revision"],
        "load_report_sha256": hashlib.sha256(load_bytes).hexdigest(),
        "metrics_report_sha256": hashlib.sha256(metrics_path.read_bytes()).hexdigest(),
        "configuration": {
            "concurrency": configuration["concurrency"],
            "measured_duration_seconds": configuration["actual_elapsed_seconds"],
            "warmup_requests": configuration["warmup_requests"],
        },
        "result": {
            "request_count": summary["request_count"],
            "requests_per_second": summary["requests_per_second"],
            "response_bytes": summary["response_bytes"],
            "transport_error_count": summary["transport_error_count"],
            "contract_mismatch_count": summary["contract_mismatch_count"],
            "server_error_count": summary["server_error_count"],
        },
        "contract_integrity_passes": (
            summary["transport_error_count"] == 0
            and summary["contract_mismatch_count"] == 0
            and summary["server_error_count"] == 0
        ),
        "load_gate_passes": load_gate["passes"],
        "failed_latency_methods": failed_methods,
        "native_metrics": {
            "billable_instance_seconds": metric_values["billable_instance_time"]["numeric"][
                "sum"
            ],
            "cpu_allocation_seconds": metric_values["cpu_allocation_time"]["numeric"]["sum"],
            "cpu_weighted_mean": _distribution(metric_values, "cpu_utilization", "weighted_mean"),
            "cpu_p95_upper_bound": _histogram(
                metric_values, "cpu_utilization", "approximate_p95_upper_bound"
            ),
            "memory_weighted_mean": _distribution(
                metric_values, "memory_utilization", "weighted_mean"
            ),
            "memory_p95_upper_bound": _histogram(
                metric_values, "memory_utilization", "approximate_p95_upper_bound"
            ),
            "memory_allocation_gibibyte_seconds": metric_values[
                "memory_allocation_time"
            ]["numeric"]["sum"],
            "request_latency_weighted_mean_ms": _distribution(
                metric_values, "request_latency", "weighted_mean"
            ),
            "request_latency_p95_upper_bound_ms": _histogram(
                metric_values, "request_latency", "approximate_p95_upper_bound"
            ),
            "request_latency_p99_upper_bound_ms": _histogram(
                metric_values, "request_latency", "approximate_p99_upper_bound"
            ),
            "max_request_concurrency_p95_upper_bound": _histogram(
                metric_values, "max_request_concurrency", "approximate_p95_upper_bound"
            ),
            "maximum_instance_count": metric_values["instance_count"]["numeric"]["maximum"],
            "startup_observation_count": metric_values["startup_latency"]["distribution"][
                "observation_count"
            ],
            "startup_weighted_mean_ms": _distribution(
                metric_values, "startup_latency", "weighted_mean"
            ),
        },
        "metrics_warnings": metrics["evidence_gate"].get("warnings", []),
    }


def _distribution(
    metrics: Mapping[str, Any], name: str, field: str
) -> float | int | None:
    return metrics[name]["distribution"][field]


def _histogram(
    metrics: Mapping[str, Any], name: str, field: str
) -> float | int | None:
    return metrics[name]["distribution"]["histogram"][field]


if __name__ == "__main__":
    raise SystemExit(main())

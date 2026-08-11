"""Capture privacy-safe Cloud Run resource evidence for one private load run."""

import argparse
import hashlib
import json
import math
import subprocess
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

_PROJECT = "trs-80"
_SERVICE = "retrostore-api-compat-candidate"
_PRIVATE_CANDIDATE_URL = "https://retrostore-api-compat-candidate-760396810462.us-central1.run.app"
_METRICS = {
    "billable_instance_time": "run.googleapis.com/container/billable_instance_time",
    "cpu_allocation_time": "run.googleapis.com/container/cpu/allocation_time",
    "cpu_utilization": "run.googleapis.com/container/cpu/utilizations",
    "instance_count": "run.googleapis.com/container/instance_count",
    "max_request_concurrency": "run.googleapis.com/container/max_request_concurrencies",
    "memory_allocation_time": "run.googleapis.com/container/memory/allocation_time",
    "memory_utilization": "run.googleapis.com/container/memory/utilizations",
    "request_count": "run.googleapis.com/request_count",
    "request_latency": "run.googleapis.com/request_latencies",
    "startup_latency": "run.googleapis.com/container/startup_latencies",
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--load-report", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--margin-seconds", type=int, default=180)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-project")
    parser.add_argument("--confirm-service")
    parser.add_argument("--confirm-revision")
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args(argv)

    source_bytes = args.load_report.read_bytes()
    load_report = json.loads(source_bytes)
    start, end = _validate_inputs(args, load_report)
    interval = {
        "start": (start - timedelta(seconds=args.margin_seconds)).isoformat(),
        "end": (end + timedelta(seconds=args.margin_seconds)).isoformat(),
        "margin_seconds": args.margin_seconds,
    }
    if not args.apply:
        report: dict[str, Any] = {
            "schema_version": 1,
            "operation": "private_api_cloud_run_metrics",
            "applied": False,
            "read_only": True,
            "project": _PROJECT,
            "service": _SERVICE,
            "revision": args.revision,
            "interval": interval,
            "metric_types": dict(sorted(_METRICS.items())),
        }
    else:
        _validate_confirmations(args)
        _require_gcloud_project()
        token = _gcloud_access_token()
        with httpx.Client(
            base_url="https://monitoring.googleapis.com",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        ) as client:
            metrics = {
                name: _summarize_time_series(
                    _list_time_series(
                        client,
                        project=_PROJECT,
                        service=_SERVICE,
                        revision=args.revision,
                        metric_type=metric_type,
                        start=interval["start"],
                        end=interval["end"],
                    )
                )
                for name, metric_type in sorted(_METRICS.items())
            }
        evidence_gate = _resource_evidence_gate(metrics, load_report)
        report = {
            "schema_version": 1,
            "operation": "private_api_cloud_run_metrics",
            "applied": True,
            "read_only": True,
            "generated_at": datetime.now(UTC).isoformat(),
            "project": _PROJECT,
            "service": _SERVICE,
            "revision": args.revision,
            "source_load_report_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "source_load_gate_passes": load_report["gate"]["passes"],
            "load_window": {
                "started_at": start.isoformat(),
                "completed_at": end.isoformat(),
            },
            "interval": interval,
            "metrics": metrics,
            "evidence_gate": evidence_gate,
            "safety": {
                "contains_access_token": False,
                "contains_request_or_response_payloads": False,
                "contains_catalog_field_values": False,
                "contains_state_tokens": False,
                "monitoring_requests_are_read_only": True,
            },
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(_console_summary(report), sort_keys=True, separators=(",", ":")))
    if args.apply and args.require_complete and not report["evidence_gate"]["passes"]:
        return 1
    return 0


def _validate_inputs(
    args: argparse.Namespace, load_report: Mapping[str, Any]
) -> tuple[datetime, datetime]:
    if load_report.get("operation") != "private_api_read_load_test":
        raise ValueError("Source must be a private API load-test report")
    if load_report.get("applied") is not True or load_report.get("read_only") is not True:
        raise ValueError("Source load test must be an applied read-only run")
    gate = load_report.get("gate")
    if not isinstance(gate, dict) or not isinstance(gate.get("passes"), bool):
        raise ValueError("Source load test must contain a completed gate result")
    if str(load_report.get("candidate_url", "")).rstrip("/") != _PRIVATE_CANDIDATE_URL:
        raise ValueError("Source load test must target the private API candidate")
    if not args.revision.startswith(f"{_SERVICE}-"):
        raise ValueError("Revision must belong to the private API candidate")
    if not 0 <= args.margin_seconds <= 900:
        raise ValueError("Monitoring margin must be between 0 and 900 seconds")
    start = _parse_timestamp(load_report.get("started_at"), "started_at")
    end = _parse_timestamp(load_report.get("generated_at"), "generated_at")
    if end <= start:
        raise ValueError("Source load-test window is not increasing")
    return start, end


def _validate_confirmations(args: argparse.Namespace) -> None:
    if args.confirm_project != _PROJECT:
        raise ValueError(f"--confirm-project must be exactly {_PROJECT}")
    if args.confirm_service != _SERVICE:
        raise ValueError(f"--confirm-service must be exactly {_SERVICE}")
    if args.confirm_revision != args.revision:
        raise ValueError("--confirm-revision must exactly match --revision")


def _parse_timestamp(value: Any, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"Source load test is missing {name}")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"Source load-test {name} must include a timezone")
    return parsed.astimezone(UTC)


def _require_gcloud_project() -> None:
    completed = subprocess.run(
        ["gcloud", "config", "get-value", "project", "--quiet"],
        check=True,
        capture_output=True,
        text=True,
    )
    configured = completed.stdout.strip()
    if configured != _PROJECT:
        raise RuntimeError(
            f"gcloud project is {configured or '<unset>'}; expected exactly {_PROJECT}"
        )


def _gcloud_access_token() -> str:
    completed = subprocess.run(
        ["gcloud", "auth", "print-access-token", "--project", _PROJECT, "--quiet"],
        check=True,
        capture_output=True,
        text=True,
    )
    token = completed.stdout.strip()
    if not token:
        raise RuntimeError("gcloud returned an empty access token")
    return token


def _list_time_series(
    client: httpx.Client,
    *,
    project: str,
    service: str,
    revision: str,
    metric_type: str,
    start: str,
    end: str,
) -> list[Mapping[str, Any]]:
    monitoring_filter = (
        f'metric.type="{metric_type}" AND '
        'resource.type="cloud_run_revision" AND '
        f'resource.labels.service_name="{service}" AND '
        f'resource.labels.revision_name="{revision}"'
    )
    params = {
        "filter": monitoring_filter,
        "interval.startTime": start,
        "interval.endTime": end,
        "view": "FULL",
        "pageSize": 100000,
    }
    series: list[Mapping[str, Any]] = []
    while True:
        response = client.get(f"/v3/projects/{project}/timeSeries", params=params)
        response.raise_for_status()
        body = response.json()
        series.extend(body.get("timeSeries", ()))
        token = body.get("nextPageToken")
        if not token:
            return series
        params["pageToken"] = token


def _summarize_time_series(series: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    numeric_values: list[float] = []
    distribution_count = 0
    distribution_weighted_sum = 0.0
    distribution_minima: list[float] = []
    distribution_maxima: list[float] = []
    point_times: list[str] = []
    label_sets: Counter[tuple[tuple[str, str], ...]] = Counter()
    value_types: Counter[str] = Counter()
    series_summaries: list[dict[str, Any]] = []
    histogram_options: Mapping[str, Any] | None = None
    histogram_counts: list[int] = []
    histogram_consistent = True

    for item in series:
        labels = tuple(
            sorted(
                (str(key), str(value))
                for key, value in item.get("metric", {}).get("labels", {}).items()
            )
        )
        label_sets[labels] += 1
        item_numeric: list[float] = []
        item_distribution_count = 0
        item_distribution_weighted_sum = 0.0
        for point in item.get("points", ()):
            interval = point.get("interval", {})
            if interval.get("endTime"):
                point_times.append(str(interval["endTime"]))
            value = point.get("value", {})
            if "int64Value" in value:
                value_types["INT64"] += 1
                numeric = float(value["int64Value"])
                numeric_values.append(numeric)
                item_numeric.append(numeric)
            elif "doubleValue" in value:
                value_types["DOUBLE"] += 1
                numeric = float(value["doubleValue"])
                numeric_values.append(numeric)
                item_numeric.append(numeric)
            elif "distributionValue" in value:
                value_types["DISTRIBUTION"] += 1
                distribution = value["distributionValue"]
                count = int(distribution.get("count", 0))
                mean = float(distribution.get("mean", 0.0))
                distribution_count += count
                distribution_weighted_sum += count * mean
                item_distribution_count += count
                item_distribution_weighted_sum += count * mean
                value_range = distribution.get("range", {})
                if "min" in value_range:
                    distribution_minima.append(float(value_range["min"]))
                if "max" in value_range:
                    distribution_maxima.append(float(value_range["max"]))
                options = distribution.get("bucketOptions")
                counts = distribution.get("bucketCounts")
                if isinstance(options, dict) and isinstance(counts, list):
                    point_counts = [int(item) for item in counts]
                    if histogram_options is None:
                        histogram_options = options
                        histogram_counts = [0] * len(point_counts)
                    if options != histogram_options:
                        histogram_consistent = False
                    else:
                        if len(point_counts) > len(histogram_counts):
                            histogram_counts.extend(
                                [0] * (len(point_counts) - len(histogram_counts))
                            )
                        for index, additional in enumerate(point_counts):
                            histogram_counts[index] += additional
            else:
                value_types["OTHER"] += 1
        series_summaries.append(
            {
                "metric_labels": dict(labels),
                "point_count": len(item.get("points", ())),
                "numeric": {
                    "count": len(item_numeric),
                    "minimum": min(item_numeric) if item_numeric else None,
                    "maximum": max(item_numeric) if item_numeric else None,
                    "sum": sum(item_numeric) if item_numeric else None,
                    "mean": sum(item_numeric) / len(item_numeric) if item_numeric else None,
                },
                "distribution": {
                    "observation_count": item_distribution_count,
                    "weighted_mean": (
                        item_distribution_weighted_sum / item_distribution_count
                        if item_distribution_count
                        else None
                    ),
                },
            }
        )

    histogram = {
        "bucket_options_consistent": histogram_consistent,
        "bucket_observation_count": sum(histogram_counts),
        "approximate_p50_upper_bound": None,
        "approximate_p95_upper_bound": None,
        "approximate_p99_upper_bound": None,
    }
    if histogram_options is not None and histogram_consistent:
        histogram.update(
            {
                "approximate_p50_upper_bound": _histogram_percentile_upper_bound(
                    histogram_options, histogram_counts, 50
                ),
                "approximate_p95_upper_bound": _histogram_percentile_upper_bound(
                    histogram_options, histogram_counts, 95
                ),
                "approximate_p99_upper_bound": _histogram_percentile_upper_bound(
                    histogram_options, histogram_counts, 99
                ),
            }
        )

    return {
        "series_count": len(series),
        "point_count": sum(value_types.values()),
        "value_type_counts": dict(sorted(value_types.items())),
        "first_point_at": min(point_times) if point_times else None,
        "last_point_at": max(point_times) if point_times else None,
        "numeric": {
            "count": len(numeric_values),
            "minimum": min(numeric_values) if numeric_values else None,
            "maximum": max(numeric_values) if numeric_values else None,
            "sum": sum(numeric_values) if numeric_values else None,
            "mean": sum(numeric_values) / len(numeric_values) if numeric_values else None,
        },
        "distribution": {
            "observation_count": distribution_count,
            "weighted_mean": (
                distribution_weighted_sum / distribution_count if distribution_count else None
            ),
            "observed_minimum": min(distribution_minima) if distribution_minima else None,
            "observed_maximum": max(distribution_maxima) if distribution_maxima else None,
            "histogram": histogram,
        },
        "metric_label_sets": [
            {"labels": dict(labels), "series_count": count}
            for labels, count in sorted(label_sets.items())
        ],
        "series_summaries": series_summaries,
    }


def _histogram_percentile_upper_bound(
    options: Mapping[str, Any], counts: Sequence[int], percentile: int
) -> float | None:
    total = sum(counts)
    if total <= 0:
        return None
    target = math.ceil(total * percentile / 100)
    cumulative = 0
    for bucket_index, count in enumerate(counts):
        cumulative += count
        if cumulative >= target:
            return _histogram_bucket_upper_bound(options, bucket_index)
    return None


def _histogram_bucket_upper_bound(options: Mapping[str, Any], bucket_index: int) -> float | None:
    if "explicitBuckets" in options:
        bounds = [float(value) for value in options["explicitBuckets"].get("bounds", ())]
        return bounds[bucket_index] if bucket_index < len(bounds) else None
    if "linearBuckets" in options:
        linear = options["linearBuckets"]
        finite = int(linear["numFiniteBuckets"])
        if bucket_index > finite:
            return None
        return float(linear.get("offset", 0)) + bucket_index * float(linear["width"])
    if "exponentialBuckets" in options:
        exponential = options["exponentialBuckets"]
        finite = int(exponential["numFiniteBuckets"])
        if bucket_index > finite:
            return None
        return float(exponential["scale"]) * float(exponential["growthFactor"]) ** bucket_index
    return None


def _resource_evidence_gate(
    metrics: Mapping[str, Mapping[str, Any]], load_report: Mapping[str, Any]
) -> dict[str, Any]:
    measured_requests = load_report.get("summary", {}).get("request_count")
    warmup_requests = load_report.get("configuration", {}).get("warmup_requests")
    if (
        isinstance(measured_requests, bool)
        or not isinstance(measured_requests, int)
        or measured_requests < 0
        or isinstance(warmup_requests, bool)
        or not isinstance(warmup_requests, int)
        or warmup_requests < 0
    ):
        raise ValueError("Source load test has invalid measured/warmup request counts")
    expected_requests = measured_requests + warmup_requests
    native_request_count = int(metrics["request_count"]["numeric"]["sum"] or 0)
    latency_observation_count = int(metrics["request_latency"]["distribution"]["observation_count"])
    required_resource_metrics = {
        "billable_instance_time": int(metrics["billable_instance_time"]["numeric"]["count"]),
        "cpu_allocation_time": int(metrics["cpu_allocation_time"]["numeric"]["count"]),
        "cpu_utilization": int(metrics["cpu_utilization"]["distribution"]["observation_count"]),
        "instance_count": int(metrics["instance_count"]["numeric"]["count"]),
        "max_request_concurrency": int(
            metrics["max_request_concurrency"]["distribution"]["observation_count"]
        ),
        "memory_allocation_time": int(metrics["memory_allocation_time"]["numeric"]["count"]),
        "memory_utilization": int(
            metrics["memory_utilization"]["distribution"]["observation_count"]
        ),
    }
    reasons = []
    warnings = []
    if max(native_request_count, latency_observation_count) < expected_requests:
        reasons.append("native_request_volume_is_incomplete")
    if native_request_count < expected_requests:
        warnings.append("native_request_count_is_lower_than_expected")
    if latency_observation_count < expected_requests:
        warnings.append("native_request_latency_count_is_lower_than_expected")
    if any(count == 0 for count in required_resource_metrics.values()):
        reasons.append("required_resource_metric_is_missing")
    return {
        "passes": not reasons,
        "expected_minimum_request_count": expected_requests,
        "native_request_count": native_request_count,
        "native_request_latency_observation_count": latency_observation_count,
        "required_resource_observation_counts": required_resource_metrics,
        "reasons": reasons,
        "warnings": warnings,
    }


def _console_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    if not report.get("applied"):
        return {
            "applied": False,
            "project": report["project"],
            "service": report["service"],
            "revision": report["revision"],
            "interval": report["interval"],
        }
    return {
        "applied": True,
        "revision": report["revision"],
        "evidence_gate": report["evidence_gate"],
        "metrics": {
            name: {
                "series_count": metric["series_count"],
                "point_count": metric["point_count"],
                "numeric": metric["numeric"],
                "distribution": metric["distribution"],
            }
            for name, metric in report["metrics"].items()
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())

"""Capture privacy-safe Cloud Run resource evidence for one private load run."""

import argparse
import hashlib
import json
import subprocess
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

_PROJECT = "trs-80"
_SERVICE = "retrostore-api-compat-candidate"
_PRIVATE_CANDIDATE_URL = (
    "https://retrostore-api-compat-candidate-760396810462.us-central1.run.app"
)
_METRICS = {
    "cpu_utilization": "run.googleapis.com/container/cpu/utilizations",
    "instance_count": "run.googleapis.com/container/instance_count",
    "max_request_concurrency": "run.googleapis.com/container/max_request_concurrencies",
    "memory_utilization": "run.googleapis.com/container/memory/utilizations",
    "request_count": "run.googleapis.com/request_count",
    "request_latency": "run.googleapis.com/request_latencies",
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
            "load_window": {
                "started_at": start.isoformat(),
                "completed_at": end.isoformat(),
            },
            "interval": interval,
            "metrics": metrics,
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
    return 0


def _validate_inputs(
    args: argparse.Namespace, load_report: Mapping[str, Any]
) -> tuple[datetime, datetime]:
    if load_report.get("operation") != "private_api_read_load_test":
        raise ValueError("Source must be a private API load-test report")
    if load_report.get("applied") is not True or load_report.get("read_only") is not True:
        raise ValueError("Source load test must be an applied read-only run")
    if load_report.get("gate", {}).get("passes") is not True:
        raise ValueError("Source load test must have passed its gate")
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

    for item in series:
        labels = tuple(
            sorted(
                (str(key), str(value))
                for key, value in item.get("metric", {}).get("labels", {}).items()
            )
        )
        label_sets[labels] += 1
        for point in item.get("points", ()):
            interval = point.get("interval", {})
            if interval.get("endTime"):
                point_times.append(str(interval["endTime"]))
            value = point.get("value", {})
            if "int64Value" in value:
                value_types["INT64"] += 1
                numeric_values.append(float(value["int64Value"]))
            elif "doubleValue" in value:
                value_types["DOUBLE"] += 1
                numeric_values.append(float(value["doubleValue"]))
            elif "distributionValue" in value:
                value_types["DISTRIBUTION"] += 1
                distribution = value["distributionValue"]
                count = int(distribution.get("count", 0))
                mean = float(distribution.get("mean", 0.0))
                distribution_count += count
                distribution_weighted_sum += count * mean
                value_range = distribution.get("range", {})
                if "min" in value_range:
                    distribution_minima.append(float(value_range["min"]))
                if "max" in value_range:
                    distribution_maxima.append(float(value_range["max"]))
            else:
                value_types["OTHER"] += 1

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
                distribution_weighted_sum / distribution_count
                if distribution_count
                else None
            ),
            "observed_minimum": min(distribution_minima) if distribution_minima else None,
            "observed_maximum": max(distribution_maxima) if distribution_maxima else None,
        },
        "metric_label_sets": [
            {"labels": dict(labels), "series_count": count}
            for labels, count in sorted(label_sets.items())
        ],
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

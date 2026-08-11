"""Guarded read-only latency and concurrency test for the private API candidate."""

import argparse
import asyncio
import json
import math
import subprocess
import time
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from retrostore.contract.exhaustive import discover_exhaustive_corpus
from retrostore.contract.observations import (
    ResponseObservation,
    compare_observations,
    observe_response,
)
from retrostore.contract.scenarios import ContractScenario

_PRIVATE_CANDIDATE_URL = "https://retrostore-api-compat-candidate-760396810462.us-central1.run.app"


@dataclass(frozen=True, slots=True)
class RequestSample:
    scenario: str
    method: str
    latency_ms: float
    status_code: int | None
    response_bytes: int
    mismatch_fields: tuple[str, ...]
    error_type: str | None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-url", default="https://retrostore.org")
    parser.add_argument("--candidate-url", required=True)
    parser.add_argument("--candidate-gcloud-identity-token-service-account", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration-seconds", type=float, default=60.0)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--max-requests", type=int, default=2000)
    parser.add_argument("--warmup-requests", type=int, default=16)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-candidate-url")
    args = parser.parse_args(argv)
    _validate_arguments(args)

    if not args.apply:
        report: dict[str, Any] = {
            "schema_version": 1,
            "operation": "private_api_read_load_test",
            "applied": False,
            "read_only": True,
            "candidate_url": args.candidate_url.rstrip("/"),
            "plan": {
                "duration_seconds": args.duration_seconds,
                "concurrency": args.concurrency,
                "max_requests": args.max_requests,
                "warmup_requests": args.warmup_requests,
                "timeout_seconds": args.timeout_seconds,
            },
        }
    else:
        if args.confirm_candidate_url != args.candidate_url:
            raise ValueError(
                "--confirm-candidate-url must exactly match --candidate-url when applying"
            )
        report = _run_applied(args)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(_console_summary(report), sort_keys=True, separators=(",", ":")))
    if report.get("applied") and not report["gate"]["passes"]:
        return 1
    return 0


def _run_applied(args: argparse.Namespace) -> dict[str, Any]:
    reference_observations, baseline_latencies, scenarios, scope = _capture_reference(
        args.reference_url, args.timeout_seconds
    )
    token = _gcloud_identity_token(
        args.candidate_url,
        args.candidate_gcloud_identity_token_service_account,
    )
    started = datetime.now(UTC)
    samples, elapsed = asyncio.run(
        execute_candidate_load(
            args.candidate_url,
            scenarios,
            reference_observations,
            headers={"Authorization": f"Bearer {token}"},
            duration_seconds=args.duration_seconds,
            concurrency=args.concurrency,
            max_requests=args.max_requests,
            warmup_requests=args.warmup_requests,
            timeout_seconds=args.timeout_seconds,
        )
    )
    performance = _performance_report(samples, baseline_latencies)
    error_count = sum(sample.error_type is not None for sample in samples)
    mismatch_count = sum(bool(sample.mismatch_fields) for sample in samples)
    server_error_count = sum(
        sample.status_code is not None and sample.status_code >= 500 for sample in samples
    )
    request_count = len(samples)
    server_error_ratio = server_error_count / request_count if request_count else 1.0
    gate = {
        "passes": (
            request_count >= 100
            and error_count == 0
            and mismatch_count == 0
            and server_error_ratio <= 0.01
            and performance["latency_gate_passes"]
        ),
        "minimum_request_count": 100,
        "maximum_transport_errors": 0,
        "maximum_contract_mismatches": 0,
        "maximum_5xx_ratio": 0.01,
        "latency_uses_provisional_front_door_thresholds": True,
    }
    return {
        "schema_version": 1,
        "operation": "private_api_read_load_test",
        "applied": True,
        "read_only": True,
        "generated_at": datetime.now(UTC).isoformat(),
        "started_at": started.isoformat(),
        "reference_url": args.reference_url.rstrip("/"),
        "candidate_url": args.candidate_url.rstrip("/"),
        "scope": scope,
        "configuration": {
            "duration_seconds": args.duration_seconds,
            "actual_elapsed_seconds": round(elapsed, 6),
            "concurrency": args.concurrency,
            "max_requests": args.max_requests,
            "warmup_requests": args.warmup_requests,
            "timeout_seconds": args.timeout_seconds,
        },
        "summary": {
            "request_count": request_count,
            "transport_error_count": error_count,
            "contract_mismatch_count": mismatch_count,
            "server_error_count": server_error_count,
            "server_error_ratio": server_error_ratio,
            "response_bytes": sum(sample.response_bytes for sample in samples),
            "requests_per_second": request_count / elapsed if elapsed else 0.0,
            "status_counts": dict(
                sorted(
                    Counter(
                        str(sample.status_code)
                        if sample.status_code is not None
                        else "transport_error"
                        for sample in samples
                    ).items()
                )
            ),
            "error_types": dict(
                sorted(
                    Counter(
                        sample.error_type for sample in samples if sample.error_type is not None
                    ).items()
                )
            ),
            "mismatch_field_counts": dict(
                sorted(
                    Counter(field for sample in samples for field in sample.mismatch_fields).items()
                )
            ),
        },
        "performance": performance,
        "gate": gate,
        "safety": {
            "contains_identity_token": False,
            "contains_request_payloads": False,
            "contains_response_payloads": False,
            "contains_catalog_field_values": False,
            "contains_state_tokens": False,
            "state_write_scenarios": 0,
        },
    }


def _capture_reference(
    base_url: str, timeout_seconds: float
) -> tuple[
    dict[str, ResponseObservation],
    dict[str, list[float]],
    tuple[ContractScenario, ...],
    dict[str, int],
]:
    with httpx.Client(
        base_url=base_url,
        follow_redirects=False,
        timeout=timeout_seconds,
    ) as client:
        corpus = discover_exhaustive_corpus(client)
        observations: dict[str, ResponseObservation] = {}
        latencies: dict[str, list[float]] = defaultdict(list)
        for scenario in corpus.scenarios:
            started = time.perf_counter()
            response = client.post(f"/api/{scenario.method.name}", content=scenario.body)
            latencies[scenario.method.name].append((time.perf_counter() - started) * 1000)
            observations[scenario.name] = observe_response(scenario, response)
    return observations, dict(latencies), corpus.scenarios, corpus.scope()


async def execute_candidate_load(
    candidate_url: str,
    scenarios: Sequence[ContractScenario],
    expected: Mapping[str, ResponseObservation],
    *,
    headers: Mapping[str, str] | None,
    duration_seconds: float,
    concurrency: int,
    max_requests: int,
    warmup_requests: int,
    timeout_seconds: float,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[tuple[RequestSample, ...], float]:
    if not scenarios or any(scenario.method.name == "uploadState" for scenario in scenarios):
        raise ValueError("Load scenarios must be a non-empty read-only sequence")
    issued = 0
    samples: list[RequestSample] = []
    async with httpx.AsyncClient(
        base_url=candidate_url,
        follow_redirects=False,
        timeout=timeout_seconds,
        headers=headers,
        transport=transport,
    ) as client:
        for ordinal in range(warmup_requests):
            scenario = scenarios[ordinal % len(scenarios)]
            await _request_sample(client, scenario, expected[scenario.name])

        started = time.perf_counter()
        deadline = started + duration_seconds

        async def worker() -> None:
            nonlocal issued
            while issued < max_requests and time.perf_counter() < deadline:
                ordinal = issued
                issued += 1
                scenario = scenarios[ordinal % len(scenarios)]
                samples.append(await _request_sample(client, scenario, expected[scenario.name]))

        await asyncio.gather(*(worker() for _ in range(concurrency)))
        elapsed = time.perf_counter() - started
    return tuple(samples), elapsed


async def _request_sample(
    client: httpx.AsyncClient,
    scenario: ContractScenario,
    expected: ResponseObservation,
) -> RequestSample:
    started = time.perf_counter()
    try:
        response = await client.post(f"/api/{scenario.method.name}", content=scenario.body)
        latency = (time.perf_counter() - started) * 1000
        actual = observe_response(scenario, response)
        differences = compare_observations(expected, actual)
        return RequestSample(
            scenario.name,
            scenario.method.name,
            latency,
            response.status_code,
            len(response.content),
            tuple(sorted(differences)),
            None,
        )
    except Exception as error:
        return RequestSample(
            scenario.name,
            scenario.method.name,
            (time.perf_counter() - started) * 1000,
            None,
            0,
            (),
            type(error).__name__,
        )


def _performance_report(
    samples: Sequence[RequestSample], baseline: Mapping[str, Sequence[float]]
) -> dict[str, Any]:
    candidate: dict[str, list[float]] = defaultdict(list)
    for sample in samples:
        if sample.error_type is None:
            candidate[sample.method].append(sample.latency_ms)
    methods: dict[str, Any] = {}
    all_pass = True
    for method in sorted(set(baseline) | set(candidate)):
        baseline_values = list(baseline.get(method, ()))
        candidate_values = candidate.get(method, [])
        baseline_p95 = _percentile(baseline_values, 95)
        baseline_p99 = _percentile(baseline_values, 99)
        candidate_p95 = _percentile(candidate_values, 95)
        candidate_p99 = _percentile(candidate_values, 99)
        p95_limit = max(baseline_p95 * 2.0, baseline_p95 + 250.0)
        p99_limit = max(baseline_p99 * 2.0, baseline_p99 + 500.0)
        passes = (
            bool(candidate_values) and candidate_p95 <= p95_limit and candidate_p99 <= p99_limit
        )
        all_pass = all_pass and passes
        methods[method] = {
            "request_count": len(candidate_values),
            "baseline_sample_count": len(baseline_values),
            "candidate_p50_ms": _finite_round(_percentile(candidate_values, 50)),
            "candidate_p95_ms": _finite_round(candidate_p95),
            "candidate_p99_ms": _finite_round(candidate_p99),
            "baseline_p95_ms": _finite_round(baseline_p95),
            "baseline_p99_ms": _finite_round(baseline_p99),
            "p95_limit_ms": _finite_round(p95_limit),
            "p99_limit_ms": _finite_round(p99_limit),
            "passes": passes,
        }
    return {"latency_gate_passes": all_pass, "methods": methods}


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return math.inf
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percentile / 100
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def _finite_round(value: float) -> float | None:
    return round(value, 3) if math.isfinite(value) else None


def _validate_arguments(args: argparse.Namespace) -> None:
    if args.reference_url.rstrip("/") != "https://retrostore.org":
        raise ValueError("Load-test reference must be https://retrostore.org")
    _validate_https_origin(args.candidate_url, "candidate")
    if args.candidate_url.rstrip("/") != _PRIVATE_CANDIDATE_URL:
        raise ValueError("Load-test candidate must be the exact private compatibility service")
    if (
        args.candidate_gcloud_identity_token_service_account
        != "retrostore-api@trs-80.iam.gserviceaccount.com"
    ):
        raise ValueError("Load test must impersonate the project API runtime identity")
    if not 1 <= args.duration_seconds <= 900:
        raise ValueError("Duration must be between 1 and 900 seconds")
    if not 1 <= args.concurrency <= 64:
        raise ValueError("Concurrency must be between 1 and 64")
    if not 100 <= args.max_requests <= 10_000:
        raise ValueError("Maximum requests must be between 100 and 10000")
    if not 0 <= args.warmup_requests <= 1000:
        raise ValueError("Warmup requests must be between 0 and 1000")
    if not 1 <= args.timeout_seconds <= 120:
        raise ValueError("Timeout must be between 1 and 120 seconds")


def _validate_https_origin(value: str, name: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"Load-test {name} must be an HTTPS origin")


def _gcloud_identity_token(audience: str, service_account: str) -> str:
    try:
        completed = subprocess.run(
            [
                "gcloud",
                "auth",
                "print-identity-token",
                f"--impersonate-service-account={service_account}",
                f"--audiences={audience.rstrip('/')}",
                "--include-email",
                "--quiet",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or "gcloud exited unsuccessfully"
        raise RuntimeError(f"Could not impersonate {service_account}: {detail}") from None
    token = completed.stdout.strip()
    if not token:
        raise RuntimeError("gcloud returned an empty identity token")
    return token


def _console_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    if not report.get("applied"):
        return {"applied": False, "plan": report["plan"]}
    return {
        "applied": True,
        "summary": report["summary"],
        "gate": report["gate"],
    }


if __name__ == "__main__":
    raise SystemExit(main())

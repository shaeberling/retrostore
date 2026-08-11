"""Audit private Cloud Run candidate drift without changing cloud resources."""

import argparse
import hashlib
import json
import subprocess
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

_PROJECT = "trs-80"
_REGION = "us-central1"
_PUBLIC_MEMBERS = frozenset({"allUsers", "allAuthenticatedUsers"})

DescribeService = Callable[[str], Mapping[str, Any]]
GetIamPolicy = Callable[[str], Mapping[str, Any]]
AnonymousStatus = Callable[[str], int]


def audit_private_candidates(
    baseline: Mapping[str, Any],
    *,
    describe_service: DescribeService,
    get_iam_policy: GetIamPolicy,
    anonymous_status: AnonymousStatus,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    now = generated_at or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")
    expected_services = _validate_baseline(baseline)
    results = []
    for expected in expected_services:
        name = expected["name"]
        actual = describe_service(name)
        policy = get_iam_policy(name)
        actual_config = _service_configuration(actual)
        expected_config = {
            key: expected[key]
            for key in (
                "name",
                "revision",
                "image",
                "service_account",
                "ingress",
                "service_max_instances",
                "container_concurrency",
                "timeout_seconds",
                "cpu",
                "memory",
            )
        }
        invokers = _invoker_members(policy)
        expected_invokers = set(expected["allowed_invokers"])
        public_members = sorted(invokers & _PUBLIC_MEMBERS)
        status = anonymous_status(expected["url"])
        checks = {
            "configuration_matches": actual_config == expected_config,
            "traffic_is_exact_revision_at_100_percent": _traffic_matches(
                actual, expected["revision"]
            ),
            "invokers_match": invokers == expected_invokers,
            "no_public_invoker": not public_members,
            "anonymous_root_denied": status == expected["anonymous_root_status"],
        }
        results.append(
            {
                "name": name,
                "revision": actual_config.get("revision"),
                "image": actual_config.get("image"),
                "anonymous_root_status": status,
                "invoker_member_count": len(invokers),
                "invoker_members_sha256": _string_set_digest(invokers),
                "public_invoker_count": len(public_members),
                "checks": checks,
                "passes": all(checks.values()),
            }
        )
    return {
        "schema_version": 1,
        "generated_at": now.astimezone(UTC).isoformat(),
        "operation": "private_cloud_run_candidate_drift_audit",
        "applied": True,
        "read_only": True,
        "project": _PROJECT,
        "region": _REGION,
        "summary": {
            "service_count": len(results),
            "passing": sum(result["passes"] for result in results),
            "failing": sum(not result["passes"] for result in results),
            "passes": all(result["passes"] for result in results),
        },
        "services": results,
        "safety": {
            "cloud_requests_are_read_only": True,
            "contains_credentials": False,
            "contains_environment_values": False,
            "contains_invoker_member_values": False,
            "production_routing_changed": False,
            "public_iam_changed": False,
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-project")
    args = parser.parse_args(argv)
    baseline = _load_json_object(args.baseline)
    if not args.apply:
        report: dict[str, Any] = {
            "schema_version": 1,
            "operation": "private_cloud_run_candidate_drift_audit",
            "applied": False,
            "read_only": True,
            "project": _PROJECT,
            "region": _REGION,
            "service_count": len(_validate_baseline(baseline)),
        }
    else:
        if args.confirm_project != _PROJECT:
            raise ValueError(f"--confirm-project must be exactly {_PROJECT}")
        _require_gcloud_project()
        report = audit_private_candidates(
            baseline,
            describe_service=_describe_service,
            get_iam_policy=_get_iam_policy,
            anonymous_status=_anonymous_status,
        )
    if args.output.exists():
        raise FileExistsError(f"Candidate status output already exists: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(_console_summary(report), separators=(",", ":"), sort_keys=True))
    return 0 if not args.apply or report["summary"]["passes"] else 1


def _validate_baseline(baseline: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if (
        baseline.get("schema_version") != 1
        or baseline.get("status") != "private_candidates_no_public_routing_authority"
        or baseline.get("project") != _PROJECT
        or baseline.get("region") != _REGION
    ):
        raise ValueError("Private candidate baseline identity is invalid")
    services = baseline.get("services")
    if not isinstance(services, list) or len(services) != 3:
        raise ValueError("Private candidate baseline must contain exactly three services")
    names: set[str] = set()
    for service in services:
        if not isinstance(service, dict):
            raise ValueError("Private candidate baseline service is invalid")
        name = service.get("name")
        url = service.get("url")
        if not isinstance(name, str) or name in names:
            raise ValueError("Private candidate service names must be unique")
        if (
            not isinstance(url, str)
            or not url.startswith(f"https://{name}-")
            or not url.endswith(".us-central1.run.app")
        ):
            raise ValueError(f"Private candidate URL is invalid: {name}")
        if service.get("anonymous_root_status") not in {401, 403}:
            raise ValueError(f"Private candidate must deny anonymous invocation: {name}")
        invokers = service.get("allowed_invokers")
        if not isinstance(invokers, list) or not invokers or set(invokers) & _PUBLIC_MEMBERS:
            raise ValueError(f"Private candidate invoker baseline is unsafe: {name}")
        names.add(name)
    safety = baseline.get("safety")
    if not isinstance(safety, dict) or any(value is not False for value in safety.values()):
        raise ValueError("Private candidate baseline unexpectedly grants authority")
    return services


def _service_configuration(service: Mapping[str, Any]) -> dict[str, Any]:
    metadata = service.get("metadata")
    spec = service.get("spec")
    status = service.get("status")
    if not all(isinstance(item, dict) for item in (metadata, spec, status)):
        raise ValueError("Cloud Run service document is incomplete")
    annotations = metadata.get("annotations", {})
    template = spec.get("template", {})
    template_spec = template.get("spec", {})
    containers = template_spec.get("containers", [])
    if (
        not isinstance(annotations, dict)
        or not isinstance(containers, list)
        or len(containers) != 1
    ):
        raise ValueError("Cloud Run service container shape is unexpected")
    container = containers[0]
    limits = container.get("resources", {}).get("limits", {})
    return {
        "name": metadata.get("name"),
        "revision": status.get("latestReadyRevisionName"),
        "image": container.get("image"),
        "service_account": template_spec.get("serviceAccountName"),
        "ingress": annotations.get("run.googleapis.com/ingress"),
        "service_max_instances": int(annotations.get("run.googleapis.com/maxScale", -1)),
        "container_concurrency": template_spec.get("containerConcurrency"),
        "timeout_seconds": template_spec.get("timeoutSeconds"),
        "cpu": limits.get("cpu"),
        "memory": limits.get("memory"),
    }


def _traffic_matches(service: Mapping[str, Any], revision: str) -> bool:
    traffic = service.get("status", {}).get("traffic", [])
    active = [entry for entry in traffic if entry.get("percent", 0) > 0]
    return (
        len(active) == 1
        and active[0].get("percent") == 100
        and active[0].get("revisionName") == revision
    )


def _invoker_members(policy: Mapping[str, Any]) -> set[str]:
    bindings = policy.get("bindings", [])
    if not isinstance(bindings, list):
        raise ValueError("Cloud Run IAM policy bindings are invalid")
    other_roles = [
        binding.get("role") for binding in bindings if binding.get("role") != "roles/run.invoker"
    ]
    if other_roles:
        raise ValueError(f"Cloud Run service has unexpected IAM roles: {other_roles!r}")
    return {
        member
        for binding in bindings
        for member in binding.get("members", [])
        if binding.get("role") == "roles/run.invoker"
    }


def _string_set_digest(values: set[str]) -> str:
    digest = hashlib.sha256()
    for value in sorted(values):
        encoded = value.encode()
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _describe_service(name: str) -> Mapping[str, Any]:
    return _run_gcloud_json(
        "run",
        "services",
        "describe",
        name,
        "--project",
        _PROJECT,
        "--region",
        _REGION,
        "--format=json",
    )


def _get_iam_policy(name: str) -> Mapping[str, Any]:
    return _run_gcloud_json(
        "run",
        "services",
        "get-iam-policy",
        name,
        "--project",
        _PROJECT,
        "--region",
        _REGION,
        "--format=json",
    )


def _anonymous_status(url: str) -> int:
    with httpx.Client(follow_redirects=False, timeout=20.0, trust_env=False) as client:
        return client.get(f"{url}/").status_code


def _run_gcloud_json(*arguments: str) -> Mapping[str, Any]:
    completed = subprocess.run(
        ["gcloud", *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise ValueError("gcloud returned a non-object JSON document")
    return value


def _require_gcloud_project() -> None:
    completed = subprocess.run(
        ["gcloud", "config", "get-value", "project"],
        check=True,
        capture_output=True,
        text=True,
    )
    if completed.stdout.strip() != _PROJECT:
        raise ValueError(f"Active gcloud project must be {_PROJECT}")


def _load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _console_summary(report: Mapping[str, Any]) -> Mapping[str, Any]:
    if report["applied"] is False:
        return {
            "applied": False,
            "project": report["project"],
            "service_count": report["service_count"],
        }
    return {
        "applied": True,
        "project": report["project"],
        "summary": report["summary"],
    }


if __name__ == "__main__":
    raise SystemExit(main())

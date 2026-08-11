"""Audit the scheduled comparator pipeline without changing cloud resources."""

import argparse
import hashlib
import json
import subprocess
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_PROJECT = "trs-80"
_REGION = "us-central1"
_PUBLIC_MEMBERS = frozenset({"allUsers", "allAuthenticatedUsers"})


def audit_comparator_runtime(
    baseline: Mapping[str, Any],
    *,
    job: Mapping[str, Any],
    job_policy: Mapping[str, Any],
    scheduler: Mapping[str, Any],
    bucket: Mapping[str, Any],
    bucket_policy: Mapping[str, Any],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    now = generated_at or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")
    _validate_baseline(baseline)
    expected_job = baseline["job"]
    expected_scheduler = baseline["scheduler"]
    expected_storage = baseline["report_storage"]
    job_invokers = _role_members(job_policy, "roles/run.invoker")
    bucket_public = _all_policy_members(bucket_policy) & _PUBLIC_MEMBERS
    checks = {
        "job_configuration_matches": _job_configuration(job) == _expected_job(expected_job),
        "job_ready_at_expected_generation": _job_is_ready(job, expected_job["generation"]),
        "job_invokers_match": job_invokers == set(expected_job["allowed_invokers"]),
        "job_has_no_public_invoker": not (job_invokers & _PUBLIC_MEMBERS),
        "scheduler_configuration_matches": _scheduler_configuration(scheduler)
        == expected_scheduler,
        "scheduler_last_attempt_succeeded": scheduler.get("status") == {},
        "report_bucket_configuration_matches": _bucket_configuration(bucket)
        == _expected_bucket(expected_storage),
        "report_prefix_creator_binding_matches": _creator_binding_matches(
            bucket_policy, expected_storage
        ),
        "report_bucket_has_no_public_member": not bucket_public,
    }
    return {
        "schema_version": 1,
        "generated_at": now.astimezone(UTC).isoformat(),
        "operation": "scheduled_comparator_runtime_drift_audit",
        "applied": True,
        "read_only": True,
        "project": _PROJECT,
        "region": _REGION,
        "summary": {
            "check_count": len(checks),
            "passing": sum(checks.values()),
            "failing": sum(not value for value in checks.values()),
            "passes": all(checks.values()),
        },
        "checks": checks,
        "evidence": {
            "job_generation": job.get("metadata", {}).get("generation"),
            "latest_execution_status": job.get("status", {})
            .get("latestCreatedExecution", {})
            .get("completionStatus"),
            "scheduler_last_attempt_present": bool(scheduler.get("lastAttemptTime")),
            "job_invoker_count": len(job_invokers),
            "job_invokers_sha256": _string_set_digest(job_invokers),
            "bucket_public_member_count": len(bucket_public),
        },
        "safety": {
            "cloud_requests_are_read_only": True,
            "contains_credentials": False,
            "contains_environment_values": False,
            "contains_iam_member_values": False,
            "contains_comparison_payloads": False,
            "production_routing_changed": False,
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
    _validate_baseline(baseline)
    if not args.apply:
        report: dict[str, Any] = {
            "schema_version": 1,
            "operation": "scheduled_comparator_runtime_drift_audit",
            "applied": False,
            "read_only": True,
            "project": _PROJECT,
            "region": _REGION,
        }
    else:
        if args.confirm_project != _PROJECT:
            raise ValueError(f"--confirm-project must be exactly {_PROJECT}")
        _require_gcloud_project()
        report = audit_comparator_runtime(
            baseline,
            job=_gcloud_json(
                "run",
                "jobs",
                "describe",
                baseline["job"]["name"],
                "--project",
                _PROJECT,
                "--region",
                _REGION,
                "--format=json",
            ),
            job_policy=_gcloud_json(
                "run",
                "jobs",
                "get-iam-policy",
                baseline["job"]["name"],
                "--project",
                _PROJECT,
                "--region",
                _REGION,
                "--format=json",
            ),
            scheduler=_gcloud_json(
                "scheduler",
                "jobs",
                "describe",
                baseline["scheduler"]["name"],
                "--project",
                _PROJECT,
                "--location",
                _REGION,
                "--format=json",
            ),
            bucket=_gcloud_json(
                "storage",
                "buckets",
                "describe",
                f"gs://{baseline['report_storage']['bucket']}",
                "--format=json",
            ),
            bucket_policy=_gcloud_json(
                "storage",
                "buckets",
                "get-iam-policy",
                f"gs://{baseline['report_storage']['bucket']}",
                "--format=json",
            ),
        )
    if args.output.exists():
        raise FileExistsError(f"Comparator status output already exists: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    console = {"applied": report["applied"], "project": _PROJECT}
    if report["applied"]:
        console["summary"] = report["summary"]
    print(json.dumps(console, separators=(",", ":"), sort_keys=True))
    return 0 if not args.apply or report["summary"]["passes"] else 1


def _validate_baseline(baseline: Mapping[str, Any]) -> None:
    if (
        baseline.get("schema_version") != 1
        or baseline.get("status") != "private_read_only_comparator_pipeline"
        or baseline.get("project") != _PROJECT
        or baseline.get("region") != _REGION
    ):
        raise ValueError("Comparator runtime baseline identity is invalid")
    job = baseline.get("job")
    scheduler = baseline.get("scheduler")
    storage = baseline.get("report_storage")
    if not all(isinstance(value, dict) for value in (job, scheduler, storage)):
        raise ValueError("Comparator runtime baseline is incomplete")
    if set(job["allowed_invokers"]) & _PUBLIC_MEMBERS:
        raise ValueError("Comparator job baseline contains a public invoker")
    if scheduler["oauth_service_account"] != job["service_account"]:
        raise ValueError("Scheduler and comparator identities differ")
    if storage["creator_member"] != f"serviceAccount:{job['service_account']}":
        raise ValueError("Report creator identity differs from comparator identity")
    if storage["prefix"] not in storage["condition_expression"]:
        raise ValueError("Report creator condition does not contain the exact prefix")
    if baseline.get("safety") is None or any(
        value is not False for value in baseline["safety"].values()
    ):
        raise ValueError("Comparator runtime baseline unexpectedly grants authority")


def _job_configuration(job: Mapping[str, Any]) -> dict[str, Any]:
    metadata = job.get("metadata", {})
    task = job.get("spec", {}).get("template", {}).get("spec", {})
    template = task.get("template", {}).get("spec", {})
    containers = template.get("containers", [])
    if len(containers) != 1:
        raise ValueError("Comparator job must contain exactly one container")
    container = containers[0]
    limits = container.get("resources", {}).get("limits", {})
    environment = {item["name"]: item.get("value") for item in container.get("env", [])}
    return {
        "name": metadata.get("name"),
        "generation": metadata.get("generation"),
        "image": container.get("image"),
        "service_account": template.get("serviceAccountName"),
        "command": container.get("command"),
        "args": container.get("args"),
        "environment": environment,
        "task_count": task.get("taskCount"),
        "max_retries": template.get("maxRetries"),
        "timeout_seconds": int(template.get("timeoutSeconds", -1)),
        "cpu": limits.get("cpu"),
        "memory": limits.get("memory"),
    }


def _expected_job(job: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in job.items() if key != "allowed_invokers"}


def _job_is_ready(job: Mapping[str, Any], generation: int) -> bool:
    status = job.get("status", {})
    ready = any(
        condition.get("type") == "Ready" and condition.get("status") == "True"
        for condition in status.get("conditions", [])
    )
    latest = status.get("latestCreatedExecution", {})
    return (
        ready
        and status.get("observedGeneration") == generation
        and latest.get("completionStatus") == "EXECUTION_SUCCEEDED"
    )


def _scheduler_configuration(scheduler: Mapping[str, Any]) -> dict[str, Any]:
    target = scheduler.get("httpTarget", {})
    oauth = target.get("oauthToken", {})
    return {
        "name": scheduler.get("name", "").rsplit("/", 1)[-1],
        "state": scheduler.get("state"),
        "schedule": scheduler.get("schedule"),
        "time_zone": scheduler.get("timeZone"),
        "attempt_deadline_seconds": _seconds(scheduler.get("attemptDeadline")),
        "http_method": target.get("httpMethod"),
        "uri": target.get("uri"),
        "oauth_service_account": oauth.get("serviceAccountEmail"),
        "oauth_scope": oauth.get("scope"),
        "body_base64": target.get("body"),
    }


def _bucket_configuration(bucket: Mapping[str, Any]) -> dict[str, Any]:
    lifecycle = bucket.get("lifecycle_config", {}).get("rule", [])
    soft_delete = bucket.get("soft_delete_policy", {}).get("retentionDurationSeconds", "0")
    return {
        "bucket": bucket.get("name"),
        "prefix": _lifecycle_prefix(lifecycle),
        "public_access_prevention": bucket.get("public_access_prevention"),
        "uniform_bucket_level_access": bucket.get("uniform_bucket_level_access"),
        "delete_age_days": _lifecycle_age(lifecycle),
        "soft_delete_days": int(soft_delete) // 86400,
    }


def _expected_bucket(storage: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: storage[key]
        for key in (
            "bucket",
            "prefix",
            "public_access_prevention",
            "uniform_bucket_level_access",
            "delete_age_days",
            "soft_delete_days",
        )
    }


def _lifecycle_prefix(rules: Sequence[Mapping[str, Any]]) -> str | None:
    matches = [
        prefix
        for rule in rules
        if rule.get("action", {}).get("type") == "Delete"
        for prefix in rule.get("condition", {}).get("matchesPrefix", [])
    ]
    return matches[0] if len(matches) == 1 else None


def _lifecycle_age(rules: Sequence[Mapping[str, Any]]) -> int | None:
    matches = [
        rule.get("condition", {}).get("age")
        for rule in rules
        if rule.get("action", {}).get("type") == "Delete"
    ]
    return matches[0] if len(matches) == 1 else None


def _creator_binding_matches(policy: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    matches = []
    for binding in policy.get("bindings", []):
        condition = binding.get("condition", {})
        if expected["creator_member"] in binding.get("members", []):
            matches.append(
                binding.get("role") == expected["creator_role"]
                and condition.get("title") == expected["condition_title"]
                and condition.get("expression") == expected["condition_expression"]
                and binding.get("members") == [expected["creator_member"]]
            )
    return matches == [True]


def _role_members(policy: Mapping[str, Any], role: str) -> set[str]:
    return {
        member
        for binding in policy.get("bindings", [])
        if binding.get("role") == role
        for member in binding.get("members", [])
    }


def _all_policy_members(policy: Mapping[str, Any]) -> set[str]:
    return {
        member for binding in policy.get("bindings", []) for member in binding.get("members", [])
    }


def _string_set_digest(values: set[str]) -> str:
    digest = hashlib.sha256()
    for value in sorted(values):
        encoded = value.encode()
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _seconds(value: Any) -> int:
    if not isinstance(value, str) or not value.endswith("s"):
        return -1
    return int(value[:-1])


def _gcloud_json(*arguments: str) -> Mapping[str, Any]:
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


if __name__ == "__main__":
    raise SystemExit(main())

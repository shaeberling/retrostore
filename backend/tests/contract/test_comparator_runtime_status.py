import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from retrostore.contract.comparator_runtime_status import audit_comparator_runtime

BASELINE_PATH = Path(__file__).parents[3] / "infra/comparator/runtime-baseline.json"


def _baseline() -> dict[str, object]:
    return json.loads(BASELINE_PATH.read_text())


def _job(baseline: dict[str, object]) -> dict[str, object]:
    expected = baseline["job"]
    return {
        "metadata": {"name": expected["name"], "generation": expected["generation"]},
        "spec": {
            "template": {
                "spec": {
                    "taskCount": expected["task_count"],
                    "template": {
                        "spec": {
                            "containers": [
                                {
                                    "command": expected["command"],
                                    "args": expected["args"],
                                    "env": [
                                        {"name": name, "value": value}
                                        for name, value in expected["environment"].items()
                                    ],
                                    "image": expected["image"],
                                    "resources": {
                                        "limits": {
                                            "cpu": expected["cpu"],
                                            "memory": expected["memory"],
                                        }
                                    },
                                }
                            ],
                            "serviceAccountName": expected["service_account"],
                            "maxRetries": expected["max_retries"],
                            "timeoutSeconds": str(expected["timeout_seconds"]),
                        }
                    },
                }
            }
        },
        "status": {
            "conditions": [{"type": "Ready", "status": "True"}],
            "observedGeneration": expected["generation"],
            "latestCreatedExecution": {"completionStatus": "EXECUTION_SUCCEEDED"},
        },
    }


def _job_policy(baseline: dict[str, object]) -> dict[str, object]:
    return {
        "bindings": [
            {
                "role": "roles/run.invoker",
                "members": baseline["job"]["allowed_invokers"],
            }
        ]
    }


def _scheduler(baseline: dict[str, object]) -> dict[str, object]:
    expected = baseline["scheduler"]
    return {
        "name": f"projects/trs-80/locations/us-central1/jobs/{expected['name']}",
        "state": expected["state"],
        "schedule": expected["schedule"],
        "timeZone": expected["time_zone"],
        "attemptDeadline": f"{expected['attempt_deadline_seconds']}s",
        "lastAttemptTime": "2026-08-10T04:17:03Z",
        "status": {},
        "httpTarget": {
            "httpMethod": expected["http_method"],
            "uri": expected["uri"],
            "body": expected["body_base64"],
            "oauthToken": {
                "serviceAccountEmail": expected["oauth_service_account"],
                "scope": expected["oauth_scope"],
            },
        },
    }


def _bucket(baseline: dict[str, object]) -> dict[str, object]:
    expected = baseline["report_storage"]
    return {
        "name": expected["bucket"],
        "public_access_prevention": expected["public_access_prevention"],
        "uniform_bucket_level_access": expected["uniform_bucket_level_access"],
        "soft_delete_policy": {
            "retentionDurationSeconds": str(expected["soft_delete_days"] * 86400)
        },
        "lifecycle_config": {
            "rule": [
                {
                    "action": {"type": "Delete"},
                    "condition": {
                        "age": expected["delete_age_days"],
                        "matchesPrefix": [expected["prefix"]],
                    },
                }
            ]
        },
    }


def _bucket_policy(baseline: dict[str, object]) -> dict[str, object]:
    expected = baseline["report_storage"]
    return {
        "bindings": [
            {
                "role": expected["creator_role"],
                "members": [expected["creator_member"]],
                "condition": {
                    "title": expected["condition_title"],
                    "expression": expected["condition_expression"],
                },
            },
            {
                "role": "roles/storage.objectViewer",
                "members": ["serviceAccount:retrostore-api@trs-80.iam.gserviceaccount.com"],
            },
        ]
    }


def _audit(baseline: dict[str, object]) -> dict[str, object]:
    return audit_comparator_runtime(
        baseline,
        job=_job(baseline),
        job_policy=_job_policy(baseline),
        scheduler=_scheduler(baseline),
        bucket=_bucket(baseline),
        bucket_policy=_bucket_policy(baseline),
        generated_at=datetime(2026, 8, 10, tzinfo=UTC),
    )


def test_comparator_runtime_audit_passes_exact_private_pipeline() -> None:
    report = _audit(_baseline())

    assert report["summary"] == {
        "check_count": 9,
        "passing": 9,
        "failing": 0,
        "passes": True,
    }
    assert "retrostore-comparator@" not in str(report)
    assert report["safety"]["contains_environment_values"] is False


def test_comparator_runtime_audit_detects_scheduler_drift() -> None:
    baseline = _baseline()
    scheduler = _scheduler(baseline)
    scheduler["schedule"] = "*/5 * * * *"

    report = audit_comparator_runtime(
        baseline,
        job=_job(baseline),
        job_policy=_job_policy(baseline),
        scheduler=scheduler,
        bucket=_bucket(baseline),
        bucket_policy=_bucket_policy(baseline),
    )

    assert report["checks"]["scheduler_configuration_matches"] is False
    assert report["summary"]["passes"] is False


def test_comparator_runtime_audit_detects_public_bucket_member() -> None:
    baseline = _baseline()
    policy = _bucket_policy(baseline)
    policy["bindings"].append(
        {"role": "roles/storage.objectViewer", "members": ["allUsers"]}
    )

    report = audit_comparator_runtime(
        baseline,
        job=_job(baseline),
        job_policy=_job_policy(baseline),
        scheduler=_scheduler(baseline),
        bucket=_bucket(baseline),
        bucket_policy=policy,
    )

    assert report["checks"]["report_bucket_has_no_public_member"] is False
    assert report["summary"]["passes"] is False


def test_comparator_runtime_baseline_rejects_public_job_invoker() -> None:
    baseline = copy.deepcopy(_baseline())
    baseline["job"]["allowed_invokers"].append("allUsers")

    with pytest.raises(ValueError, match="public invoker"):
        _audit(baseline)

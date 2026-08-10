import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from retrostore.contract.private_candidate_status import audit_private_candidates

BASELINE_PATH = (
    Path(__file__).parents[3] / "infra/cloud-run/private-candidate-baseline.json"
)


def _baseline() -> dict[str, object]:
    return json.loads(BASELINE_PATH.read_text())


def _service(expected: dict[str, object]) -> dict[str, object]:
    return {
        "metadata": {
            "name": expected["name"],
            "annotations": {
                "run.googleapis.com/ingress": expected["ingress"],
                "run.googleapis.com/maxScale": str(expected["service_max_instances"]),
            },
        },
        "spec": {
            "template": {
                "spec": {
                    "serviceAccountName": expected["service_account"],
                    "containerConcurrency": expected["container_concurrency"],
                    "timeoutSeconds": expected["timeout_seconds"],
                    "containers": [
                        {
                            "image": expected["image"],
                            "resources": {
                                "limits": {
                                    "cpu": expected["cpu"],
                                    "memory": expected["memory"],
                                }
                            },
                        }
                    ],
                }
            }
        },
        "status": {
            "latestReadyRevisionName": expected["revision"],
            "traffic": [
                {"revisionName": expected["revision"], "percent": 100},
                {"revisionName": "older-tagged-revision", "tag": "older"},
            ],
        },
    }


def _policy(expected: dict[str, object]) -> dict[str, object]:
    return {
        "bindings": [
            {
                "role": "roles/run.invoker",
                "members": expected["allowed_invokers"],
            }
        ]
    }


def test_private_candidate_drift_audit_passes_exact_private_baseline() -> None:
    baseline = _baseline()
    services = {item["name"]: item for item in baseline["services"]}

    report = audit_private_candidates(
        baseline,
        describe_service=lambda name: _service(services[name]),
        get_iam_policy=lambda name: _policy(services[name]),
        anonymous_status=lambda _url: 403,
        generated_at=datetime(2026, 8, 10, tzinfo=UTC),
    )

    assert report["summary"] == {
        "service_count": 3,
        "passing": 3,
        "failing": 0,
        "passes": True,
    }
    assert all(result["public_invoker_count"] == 0 for result in report["services"])
    assert "saschah@gmail.com" not in str(report)
    assert report["safety"]["contains_invoker_member_values"] is False


def test_private_candidate_drift_audit_reports_image_and_traffic_drift() -> None:
    baseline = _baseline()
    services = {item["name"]: item for item in baseline["services"]}

    def describe(name: str) -> dict[str, object]:
        service = _service(services[name])
        if name == "retrostore-api-preview":
            service["spec"]["template"]["spec"]["containers"][0]["image"] = "changed"
            service["status"]["traffic"][0]["percent"] = 50
        return service

    report = audit_private_candidates(
        baseline,
        describe_service=describe,
        get_iam_policy=lambda name: _policy(services[name]),
        anonymous_status=lambda _url: 403,
    )

    result = next(
        item for item in report["services"] if item["name"] == "retrostore-api-preview"
    )
    assert result["checks"]["configuration_matches"] is False
    assert result["checks"]["traffic_is_exact_revision_at_100_percent"] is False
    assert report["summary"]["passes"] is False


def test_private_candidate_drift_audit_detects_public_invoker() -> None:
    baseline = _baseline()
    services = {item["name"]: item for item in baseline["services"]}

    def policy(name: str) -> dict[str, object]:
        value = _policy(services[name])
        if name == "retrostore-admin-candidate":
            value["bindings"][0]["members"] = [
                *value["bindings"][0]["members"],
                "allUsers",
            ]
        return value

    report = audit_private_candidates(
        baseline,
        describe_service=lambda name: _service(services[name]),
        get_iam_policy=policy,
        anonymous_status=lambda _url: 403,
    )

    result = next(
        item
        for item in report["services"]
        if item["name"] == "retrostore-admin-candidate"
    )
    assert result["checks"]["no_public_invoker"] is False
    assert result["public_invoker_count"] == 1
    assert report["summary"]["passes"] is False


def test_private_candidate_baseline_rejects_public_member() -> None:
    baseline = copy.deepcopy(_baseline())
    baseline["services"][0]["allowed_invokers"].append("allUsers")

    with pytest.raises(ValueError, match="invoker baseline is unsafe"):
        audit_private_candidates(
            baseline,
            describe_service=lambda _name: {},
            get_iam_policy=lambda _name: {},
            anonymous_status=lambda _url: 403,
        )

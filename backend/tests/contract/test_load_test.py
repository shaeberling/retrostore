import asyncio
import json
from pathlib import Path

import httpx
import pytest

import retrostore.contract.load_test as load_test
from retrostore.contract.observations import observe_response
from retrostore.contract.scenarios import ContractScenario, ScenarioCategory
from retrostore.contracts import PUBLIC_API_METHODS
from retrostore.generated import ApiProtos_pb2 as api_pb

_CANDIDATE = (
    "https://retrostore-api-compat-candidate-760396810462.us-central1.run.app"
)
_SERVICE_ACCOUNT = "retrostore-api@trs-80.iam.gserviceaccount.com"


def _arguments(output: Path) -> list[str]:
    return [
        "--candidate-url",
        _CANDIDATE,
        "--candidate-gcloud-identity-token-service-account",
        _SERVICE_ACCOUNT,
        "--output",
        str(output),
    ]


def test_dry_run_makes_no_network_or_identity_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "plan.json"
    monkeypatch.setattr(
        load_test,
        "_run_applied",
        lambda args: pytest.fail("dry run attempted network execution"),
    )

    assert load_test.main(_arguments(output)) == 0

    report = json.loads(output.read_text())
    assert report["applied"] is False
    assert report["read_only"] is True
    assert report["plan"]["concurrency"] == 8


def test_apply_requires_exact_candidate_confirmation_before_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        load_test,
        "_run_applied",
        lambda args: pytest.fail("confirmation failure attempted network execution"),
    )

    with pytest.raises(ValueError, match="confirm-candidate-url"):
        load_test.main([*_arguments(tmp_path / "report.json"), "--apply"])


def test_rejects_any_other_run_app_hostname_before_network(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path / "report.json")
    arguments[1] = "https://retrostore-api-compat-candidate-attacker.run.app"

    with pytest.raises(ValueError, match="exact private compatibility service"):
        load_test.main(arguments)


def test_async_load_compares_every_response_without_storing_payloads() -> None:
    request = api_pb.GetAppParams(app_id="app")
    scenario = ContractScenario(
        name="get",
        method=PUBLIC_API_METHODS["getApp"],
        body=request.SerializeToString(),
        category=ScenarioCategory.SUCCESS,
    )
    body = api_pb.ApiResponseApps(success=True).SerializeToString()
    expected = observe_response(
        scenario,
        httpx.Response(
            200,
            headers={
                "content-type": "application/octet-stream",
                "access-control-allow-origin": "*",
            },
            content=body,
        ),
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "content-type": "application/octet-stream",
                "access-control-allow-origin": "*",
            },
            content=body,
        )

    samples, elapsed = asyncio.run(
        load_test.execute_candidate_load(
            _CANDIDATE,
            (scenario,),
            {scenario.name: expected},
            headers=None,
            duration_seconds=1,
            concurrency=2,
            max_requests=4,
            warmup_requests=1,
            timeout_seconds=5,
            transport=httpx.MockTransport(handler),
        )
    )

    assert elapsed > 0
    assert len(samples) == 4
    assert all(sample.status_code == 200 for sample in samples)
    assert all(sample.mismatch_fields == () for sample in samples)
    assert all(sample.error_type is None for sample in samples)


def test_performance_gate_uses_multiplier_or_fixed_delta_whichever_is_larger() -> None:
    samples = tuple(
        load_test.RequestSample("scenario", "getApp", latency, 200, 1, (), None)
        for latency in (100.0, 110.0, 120.0)
    )

    report = load_test._performance_report(samples, {"getApp": [100.0]})

    assert report["latency_gate_passes"] is True
    assert report["methods"]["getApp"]["p95_limit_ms"] == 350.0

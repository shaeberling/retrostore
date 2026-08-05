from retrostore.contract.scenarios import safe_baseline_scenarios, safe_legacy_json_scenarios
from retrostore.contracts import PUBLIC_API_METHODS
from retrostore.generated import ApiProtos_pb2 as api_pb


def test_safe_baseline_covers_every_public_method_once() -> None:
    scenarios = safe_baseline_scenarios()
    assert {scenario.method.name for scenario in scenarios} == set(PUBLIC_API_METHODS)
    assert len(scenarios) == len(PUBLIC_API_METHODS)


def test_upload_baseline_is_invalid_and_cannot_allocate_a_token() -> None:
    upload = next(
        scenario for scenario in safe_baseline_scenarios() if scenario.method.name == "uploadState"
    )
    request = api_pb.UploadSystemStateParams.FromString(upload.body)
    assert len(request.state.memoryRegions) == 1
    assert request.state.memoryRegions[0].start == -1


def test_legacy_json_baseline_is_limited_to_supported_methods() -> None:
    scenarios = safe_legacy_json_scenarios()
    assert {scenario.method.name for scenario in scenarios} == {
        "getApp",
        "listApps",
        "fetchMediaImages",
    }
    assert all(scenario.request_format == "legacy_json" for scenario in scenarios)

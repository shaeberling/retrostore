import httpx

from retrostore.contract.observations import (
    compare_observations,
    normalize_protobuf,
    observe_response,
)
from retrostore.contract.scenarios import safe_baseline_scenarios
from retrostore.generated import ApiProtos_pb2 as api_pb


def test_protobuf_normalization_preserves_defaults_and_order() -> None:
    response = api_pb.ApiResponseApps(success=True, message="ok")
    response.app.add(id="2", name="Zulu")
    response.app.add(id="1", name="Alpha")

    normalized = normalize_protobuf(api_pb.ApiResponseApps, response.SerializeToString())

    assert normalized["success"] is True
    assert normalized["app"][0]["id"] == "2"
    assert normalized["app"][1]["id"] == "1"
    assert normalized["app"][0]["release_year"] == 0


def test_observation_tracks_transport_and_semantic_body() -> None:
    scenario = next(
        scenario for scenario in safe_baseline_scenarios() if scenario.method.name == "getApp"
    )
    body = api_pb.ApiResponseApps(success=False, message="App not found.").SerializeToString()
    response = httpx.Response(
        200,
        headers={
            "content-type": "application/octet-stream",
            "access-control-allow-origin": "*",
        },
        content=body,
    )

    observation = observe_response(scenario, response)

    assert observation.status_code == 200
    assert observation.content_type == "application/octet-stream"
    assert observation.access_control_allow_origin == "*"
    assert observation.semantic_body == {
        "success": False,
        "message": "App not found.",
        "app": [],
    }


def test_comparison_reports_semantic_difference_not_wire_order() -> None:
    scenario = next(
        scenario for scenario in safe_baseline_scenarios() if scenario.method.name == "getApp"
    )
    expected_response = httpx.Response(
        200,
        headers={"content-type": "application/octet-stream"},
        content=api_pb.ApiResponseApps(success=False, message="one").SerializeToString(),
    )
    actual_response = httpx.Response(
        200,
        headers={"content-type": "application/octet-stream"},
        content=api_pb.ApiResponseApps(success=False, message="longer").SerializeToString(),
    )

    differences = compare_observations(
        observe_response(scenario, expected_response),
        observe_response(scenario, actual_response),
    )

    assert set(differences) == {"body_length", "semantic_body"}

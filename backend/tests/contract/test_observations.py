import httpx

from retrostore.contract.observations import (
    MAX_INLINE_BODY_BYTES,
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
    assert observation.category == "baseline"
    assert observation.semantic_body == {
        "success": False,
        "message": "App not found.",
        "app": [],
    }


def test_protobuf_normalization_replaces_binary_contents_with_size_and_hash() -> None:
    response = api_pb.ApiResponseMediaImages(success=True)
    response.mediaImage.add(filename="command.cmd", data=b"payload")

    normalized = normalize_protobuf(
        api_pb.ApiResponseMediaImages,
        response.SerializeToString(),
    )

    assert normalized["mediaImage"][0]["data"] == {
        "size": 7,
        "sha256": "239f59ed55e737c77147cf55ad0c1b030b6d7ee748a7426952f9b852d5a935e5",
    }


def test_large_response_body_is_hashed_but_not_inlined() -> None:
    scenario = next(
        scenario for scenario in safe_baseline_scenarios() if scenario.method.name == "getApp"
    )
    response = httpx.Response(
        500,
        headers={"content-type": "text/html"},
        content=b"x" * (MAX_INLINE_BODY_BYTES + 1),
    )

    observation = observe_response(scenario, response)

    assert observation.body_length == MAX_INLINE_BODY_BYTES + 1
    assert observation.body_base64 is None
    assert observation.semantic_body is None


def test_non_protobuf_error_response_is_compared_by_body_hash() -> None:
    scenario = next(
        scenario for scenario in safe_baseline_scenarios() if scenario.method.name == "getApp"
    )
    expected = observe_response(
        scenario,
        httpx.Response(500, headers={"content-type": "text/html"}, content=b"one"),
    )
    actual = observe_response(
        scenario,
        httpx.Response(500, headers={"content-type": "text/html"}, content=b"two"),
    )

    differences = compare_observations(expected, actual)

    assert set(differences) == {"body_sha256"}


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

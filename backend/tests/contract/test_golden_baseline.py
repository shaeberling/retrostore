import base64
import hashlib
import json
from collections import Counter
from pathlib import Path

from retrostore.contract.observations import MAX_INLINE_BODY_BYTES, normalize_protobuf
from retrostore.contract.scenarios import (
    FIXTURE_APP_ID,
    FIXTURE_APP_NAME,
    FIXTURE_COMMAND_SIZE,
    ScenarioCategory,
    all_safe_scenarios,
)
from retrostore.contracts import ResponseKind

GOLDEN = Path(__file__).parent / "golden" / "live-safe-baseline.json"
EXPECTED_SERVER_ERRORS = {
    "list_apps_negative_start",
    "fetch_media_region_missing_file",
    "fetch_media_images_malformed_protobuf",
    "fetch_media_image_refs_malformed_protobuf",
}


def _golden() -> dict[str, object]:
    return json.loads(GOLDEN.read_text())


def _observations_by_name() -> dict[str, dict[str, object]]:
    return {value["scenario"]: value for value in _golden()["observations"]}


def test_reviewed_live_baseline_covers_every_safe_scenario() -> None:
    data = _golden()
    scenarios = all_safe_scenarios()
    expected = {scenario.name for scenario in scenarios}

    assert data["schema_version"] == 2
    assert data["base_url"] == "https://retrostore.org"
    assert data["scenario_count"] == len(scenarios) == 45
    assert {observation["scenario"] for observation in data["observations"]} == expected
    assert Counter(observation["category"] for observation in data["observations"]) == {
        ScenarioCategory.BASELINE: 12,
        ScenarioCategory.SUCCESS: 9,
        ScenarioCategory.BOUNDARY: 15,
        ScenarioCategory.MALFORMED: 9,
    }


def test_reviewed_live_baseline_transport_behavior() -> None:
    observations = _observations_by_name()
    actual_server_errors = {
        name for name, observation in observations.items() if observation["status_code"] == 500
    }
    assert actual_server_errors == EXPECTED_SERVER_ERRORS

    for name, observation in observations.items():
        if name in EXPECTED_SERVER_ERRORS:
            assert observation["content_type"] == "text/html"
            assert observation["access_control_allow_origin"] is None
        else:
            assert observation["status_code"] == 200
            assert observation["content_type"] == "application/octet-stream"
            assert observation["access_control_allow_origin"] == "*"


def test_reviewed_live_baseline_bodies_match_hashes_and_semantics() -> None:
    data = _golden()
    scenarios = {scenario.name: scenario for scenario in all_safe_scenarios()}

    for observation in data["observations"]:
        encoded_body = observation["body_base64"]
        assert len(observation["body_sha256"]) == 64
        if encoded_body is None:
            assert observation["body_length"] > MAX_INLINE_BODY_BYTES
            continue

        body = base64.b64decode(encoded_body)
        assert len(body) == observation["body_length"]
        assert hashlib.sha256(body).hexdigest() == observation["body_sha256"]

        scenario = scenarios[observation["scenario"]]
        if observation["semantic_body"] is not None:
            assert scenario.method.response_kind == ResponseKind.PROTOBUF
            assert scenario.method.response_type is not None
            assert (
                normalize_protobuf(scenario.method.response_type, body)
                == observation["semantic_body"]
            )


def test_success_fixture_freezes_catalog_media_and_range_behavior() -> None:
    observations = _observations_by_name()

    app = observations["get_app_existing"]["semantic_body"]["app"][0]
    assert (app["id"], app["name"]) == (FIXTURE_APP_ID, FIXTURE_APP_NAME)

    first_page = observations["list_apps_first_page"]["semantic_body"]["app"]
    assert [app["name"] for app in first_page] == ["Armored Patrol", "Attack Force"]
    last_page = observations["list_apps_last_page_truncated"]["semantic_body"]["app"]
    assert [app["name"] for app in last_page] == ["Zaxxon"]

    command = observations["fetch_media_images_command"]["semantic_body"]["mediaImage"]
    assert len(command) == 1
    assert command[0]["filename"] == "command.CMD"
    assert command[0]["data"] == {
        "size": FIXTURE_COMMAND_SIZE,
        "sha256": "312f570af4c76ed5f3ba50a0e68ba02a9188ebc0f49f459f6ffd751812d1f6d3",
    }

    refs = observations["fetch_media_refs_all"]["semantic_body"]["mediaImageRef"]
    assert [(item["type"], item["size"]) for item in refs] == [
        ("DISK", 98_304),
        ("COMMAND", FIXTURE_COMMAND_SIZE),
    ]
    assert observations["fetch_media_region_prefix"]["body_length"] == 16
    assert observations["fetch_media_region_tail_truncated"]["body_length"] == 8
    assert observations["fetch_media_region_at_eof"]["body_length"] == 0


def test_legacy_media_success_is_compact_but_content_verified() -> None:
    observation = _observations_by_name()["fetch_media_images_legacy_json_existing"]
    assert observation["body_length"] == 101_864
    assert observation["body_base64"] is None

    images = observation["semantic_body"]["mediaImage"]
    assert len(images) == 7
    populated = [image for image in images if image["data"]["size"]]
    assert [(image["type"], image["data"]["size"]) for image in populated] == [
        ("DISK", 98_304),
        ("COMMAND", FIXTURE_COMMAND_SIZE),
    ]


def test_write_method_observations_remain_rejected() -> None:
    observations = _observations_by_name()
    assert observations["upload_state_invalid_region"]["semantic_body"]["success"] is False
    assert observations["upload_state_malformed_protobuf"]["semantic_body"]["success"] is False

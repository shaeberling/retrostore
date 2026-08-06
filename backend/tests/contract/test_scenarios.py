from google.protobuf.message import DecodeError

from retrostore.contract.scenarios import (
    CATALOG_COUNT_AT_CAPTURE,
    FIXTURE_APP_ID,
    FIXTURE_COMMAND_FILENAME,
    FIXTURE_COMMAND_SIZE,
    MALFORMED_PROTOBUF,
    ScenarioCategory,
    all_safe_scenarios,
    safe_baseline_scenarios,
    safe_boundary_scenarios,
    safe_legacy_json_scenarios,
    safe_malformed_scenarios,
    safe_success_scenarios,
)
from retrostore.contracts import PUBLIC_API_METHODS
from retrostore.generated import ApiProtos_pb2 as api_pb


def test_safe_baseline_covers_every_public_method_once() -> None:
    scenarios = safe_baseline_scenarios()
    assert {scenario.method.name for scenario in scenarios} == set(PUBLIC_API_METHODS)
    assert len(scenarios) == len(PUBLIC_API_METHODS)
    assert all(scenario.category == ScenarioCategory.BASELINE for scenario in scenarios)


def test_every_write_scenario_is_rejected_before_state_storage() -> None:
    writes = [scenario for scenario in all_safe_scenarios() if scenario.method.writes_state]
    assert {scenario.name for scenario in writes} == {
        "upload_state_invalid_region",
        "upload_state_malformed_protobuf",
    }

    for scenario in writes:
        try:
            request = api_pb.UploadSystemStateParams.FromString(scenario.body)
        except DecodeError:
            continue
        assert request.state.memoryRegions
        assert any(region.start < 0 for region in request.state.memoryRegions)


def test_success_fixture_covers_catalog_media_metadata_payload_and_range() -> None:
    scenarios = {scenario.name: scenario for scenario in safe_success_scenarios()}

    get_app = api_pb.GetAppParams.FromString(scenarios["get_app_existing"].body)
    assert get_app.app_id == FIXTURE_APP_ID

    media = api_pb.FetchMediaImagesParams.FromString(
        scenarios["fetch_media_images_command"].body
    )
    assert media.app_id == FIXTURE_APP_ID
    assert list(media.media_type) == [api_pb.COMMAND]

    region = api_pb.FetchMediaImageRegionParams.FromString(
        scenarios["fetch_media_region_prefix"].body
    )
    assert region.token == f"{FIXTURE_APP_ID}/{FIXTURE_COMMAND_FILENAME}"
    assert (region.start, region.length) == (0, 16)


def test_boundary_corpus_covers_catalog_and_media_edges() -> None:
    scenarios = {scenario.name: scenario for scenario in safe_boundary_scenarios()}

    last_page = api_pb.ListAppsParams.FromString(
        scenarios["list_apps_last_page_truncated"].body
    )
    assert (last_page.start, last_page.num) == (CATALOG_COUNT_AT_CAPTURE - 1, 2)

    tail = api_pb.FetchMediaImageRegionParams.FromString(
        scenarios["fetch_media_region_tail_truncated"].body
    )
    assert (tail.start, tail.length) == (FIXTURE_COMMAND_SIZE - 8, 32)

    at_eof = api_pb.FetchMediaImageRegionParams.FromString(
        scenarios["fetch_media_region_at_eof"].body
    )
    assert (at_eof.start, at_eof.length) == (FIXTURE_COMMAND_SIZE, 1)


def test_malformed_corpus_covers_every_method_with_invalid_protobuf() -> None:
    scenarios = safe_malformed_scenarios()
    assert {scenario.method.name for scenario in scenarios} == set(PUBLIC_API_METHODS)
    assert all(scenario.body == MALFORMED_PROTOBUF for scenario in scenarios)
    assert all(scenario.category == ScenarioCategory.MALFORMED for scenario in scenarios)


def test_legacy_json_corpus_is_limited_to_supported_methods_and_has_successes() -> None:
    scenarios = safe_legacy_json_scenarios()
    assert {scenario.method.name for scenario in scenarios} == {
        "getApp",
        "listApps",
        "fetchMediaImages",
    }
    assert all(scenario.request_format == "legacy_json" for scenario in scenarios)
    assert sum(scenario.category == ScenarioCategory.SUCCESS for scenario in scenarios) == 3


def test_complete_corpus_has_unique_names_and_all_categories() -> None:
    scenarios = all_safe_scenarios()
    assert len({scenario.name for scenario in scenarios}) == len(scenarios)
    assert {scenario.category for scenario in scenarios} == set(ScenarioCategory)

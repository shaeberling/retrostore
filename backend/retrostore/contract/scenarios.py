"""Mutation-safe compatibility requests for the frozen public API."""

from dataclasses import dataclass
from enum import StrEnum

from google.protobuf.message import DecodeError, Message

from retrostore.contracts import PUBLIC_API_METHODS, ApiMethodContract
from retrostore.generated import ApiProtos_pb2 as api_pb

MISSING_APP_ID = "__retrostore_contract_missing__"
MISSING_STATE_TOKEN = 1
MALFORMED_PROTOBUF = b"\x80"

# Public catalog fixture selected on 2026-08-06. Its command image is the
# smallest command payload in the catalog, keeping the checked-in corpus small.
FIXTURE_APP_ID = "259847aa-ce3a-48bb-a037-e392beb96b22"
FIXTURE_APP_NAME = "Space Invaders (Model I Edition)"
FIXTURE_COMMAND_FILENAME = "command.CMD"
FIXTURE_COMMAND_SIZE = 3_477
FIXTURE_COMMAND_TOKEN = f"{FIXTURE_APP_ID}/{FIXTURE_COMMAND_FILENAME}"
CATALOG_COUNT_AT_CAPTURE = 32


class ScenarioCategory(StrEnum):
    BASELINE = "baseline"
    SUCCESS = "success"
    BOUNDARY = "boundary"
    MALFORMED = "malformed"


@dataclass(frozen=True, slots=True)
class ContractScenario:
    name: str
    method: ApiMethodContract
    body: bytes
    request_format: str = "protobuf"
    category: ScenarioCategory = ScenarioCategory.BASELINE


def _protobuf(
    name: str,
    method_name: str,
    request: Message,
    *,
    category: ScenarioCategory = ScenarioCategory.BASELINE,
) -> ContractScenario:
    return ContractScenario(
        name=name,
        method=PUBLIC_API_METHODS[method_name],
        body=request.SerializeToString(),
        category=category,
    )


def _malformed(name: str, method_name: str) -> ContractScenario:
    return ContractScenario(
        name=name,
        method=PUBLIC_API_METHODS[method_name],
        body=MALFORMED_PROTOBUF,
        category=ScenarioCategory.MALFORMED,
    )


def safe_baseline_scenarios() -> tuple[ContractScenario, ...]:
    """Return one established non-mutating error request per public method."""

    invalid_state = api_pb.UploadSystemStateParams()
    invalid_state.state.memoryRegions.add(start=-1, length=0, data=b"")

    return (
        _protobuf("get_app_missing_id", "getApp", api_pb.GetAppParams()),
        _protobuf(
            "list_apps_out_of_range",
            "listApps",
            api_pb.ListAppsParams(start=2_147_483_647, num=1),
        ),
        _protobuf(
            "list_apps_nano_out_of_range",
            "listAppsNano",
            api_pb.ListAppsParams(start=2_147_483_647, num=1),
        ),
        _protobuf(
            "fetch_media_images_missing_id",
            "fetchMediaImages",
            api_pb.FetchMediaImagesParams(),
        ),
        _protobuf(
            "fetch_media_refs_missing_id",
            "fetchMediaImageRefs",
            api_pb.FetchMediaImageRefsParams(),
        ),
        _protobuf(
            "fetch_media_region_bad_token",
            "fetchMediaImageRegion",
            api_pb.FetchMediaImageRegionParams(token="invalid", start=0, length=1),
        ),
        _protobuf("upload_state_invalid_region", "uploadState", invalid_state),
        _protobuf(
            "download_state_bad_token",
            "downloadState",
            api_pb.DownloadSystemStateParams(token=-1),
        ),
        _protobuf(
            "download_state_region_bad_token",
            "downloadStateMemoryRegion",
            api_pb.DownloadSystemStateMemoryRegionParams(token=-1, start=1, length=1),
        ),
    )


def safe_success_scenarios() -> tuple[ContractScenario, ...]:
    category = ScenarioCategory.SUCCESS
    return (
        _protobuf(
            "get_app_existing",
            "getApp",
            api_pb.GetAppParams(app_id=FIXTURE_APP_ID),
            category=category,
        ),
        _protobuf(
            "list_apps_first_page",
            "listApps",
            api_pb.ListAppsParams(start=0, num=2),
            category=category,
        ),
        _protobuf(
            "list_apps_nano_first_page",
            "listAppsNano",
            api_pb.ListAppsParams(start=0, num=2),
            category=category,
        ),
        _protobuf(
            "fetch_media_images_command",
            "fetchMediaImages",
            api_pb.FetchMediaImagesParams(
                app_id=FIXTURE_APP_ID,
                media_type=[api_pb.COMMAND],
            ),
            category=category,
        ),
        _protobuf(
            "fetch_media_refs_all",
            "fetchMediaImageRefs",
            api_pb.FetchMediaImageRefsParams(app_id=FIXTURE_APP_ID),
            category=category,
        ),
        _protobuf(
            "fetch_media_region_prefix",
            "fetchMediaImageRegion",
            api_pb.FetchMediaImageRegionParams(
                token=FIXTURE_COMMAND_TOKEN,
                start=0,
                length=16,
            ),
            category=category,
        ),
    )


def safe_boundary_scenarios() -> tuple[ContractScenario, ...]:
    category = ScenarioCategory.BOUNDARY
    command_filter = api_pb.ListAppsParams.Trs80Params(media_types=[api_pb.COMMAND])
    return (
        _protobuf(
            "get_app_not_found",
            "getApp",
            api_pb.GetAppParams(app_id=MISSING_APP_ID),
            category=category,
        ),
        _protobuf(
            "list_apps_zero_count",
            "listApps",
            api_pb.ListAppsParams(start=0, num=0),
            category=category,
        ),
        _protobuf(
            "list_apps_negative_count",
            "listApps",
            api_pb.ListAppsParams(start=0, num=-1),
            category=category,
        ),
        _protobuf(
            "list_apps_negative_start",
            "listApps",
            api_pb.ListAppsParams(start=-1, num=1),
            category=category,
        ),
        _protobuf(
            "list_apps_last_page_truncated",
            "listApps",
            api_pb.ListAppsParams(start=CATALOG_COUNT_AT_CAPTURE - 1, num=2),
            category=category,
        ),
        _protobuf(
            "list_apps_empty_search_result",
            "listApps",
            api_pb.ListAppsParams(start=0, num=5, query=MISSING_APP_ID),
            category=category,
        ),
        _protobuf(
            "list_apps_command_filter",
            "listApps",
            api_pb.ListAppsParams(start=0, num=2, trs80=command_filter),
            category=category,
        ),
        _protobuf(
            "fetch_media_images_unknown_filter",
            "fetchMediaImages",
            api_pb.FetchMediaImagesParams(
                app_id=FIXTURE_APP_ID,
                media_type=[api_pb.UNKNOWN],
            ),
            category=category,
        ),
        _protobuf(
            "fetch_media_refs_command_filter",
            "fetchMediaImageRefs",
            api_pb.FetchMediaImageRefsParams(
                app_id=FIXTURE_APP_ID,
                media_type=[api_pb.COMMAND],
            ),
            category=category,
        ),
        _protobuf(
            "fetch_media_region_tail_truncated",
            "fetchMediaImageRegion",
            api_pb.FetchMediaImageRegionParams(
                token=FIXTURE_COMMAND_TOKEN,
                start=FIXTURE_COMMAND_SIZE - 8,
                length=32,
            ),
            category=category,
        ),
        _protobuf(
            "fetch_media_region_at_eof",
            "fetchMediaImageRegion",
            api_pb.FetchMediaImageRegionParams(
                token=FIXTURE_COMMAND_TOKEN,
                start=FIXTURE_COMMAND_SIZE,
                length=1,
            ),
            category=category,
        ),
        _protobuf(
            "fetch_media_region_oversized_length",
            "fetchMediaImageRegion",
            api_pb.FetchMediaImageRegionParams(
                token=FIXTURE_COMMAND_TOKEN,
                start=0,
                length=(10 << 18) + 1,
            ),
            category=category,
        ),
        _protobuf(
            "fetch_media_region_missing_file",
            "fetchMediaImageRegion",
            api_pb.FetchMediaImageRegionParams(
                token=f"{FIXTURE_APP_ID}/missing.bin",
                start=0,
                length=1,
            ),
            category=category,
        ),
        _protobuf(
            "download_state_missing_positive_token",
            "downloadState",
            api_pb.DownloadSystemStateParams(token=MISSING_STATE_TOKEN),
            category=category,
        ),
        _protobuf(
            "download_state_region_missing_positive_token",
            "downloadStateMemoryRegion",
            api_pb.DownloadSystemStateMemoryRegionParams(
                token=MISSING_STATE_TOKEN,
                start=1,
                length=4,
            ),
            category=category,
        ),
    )


def safe_malformed_scenarios() -> tuple[ContractScenario, ...]:
    return tuple(
        _malformed(f"{_snake_case(method_name)}_malformed_protobuf", method_name)
        for method_name in PUBLIC_API_METHODS
    )


def safe_legacy_json_scenarios() -> tuple[ContractScenario, ...]:
    return (
        ContractScenario(
            name="get_app_legacy_json_missing_id",
            method=PUBLIC_API_METHODS["getApp"],
            body=(f'{{"appId":"{MISSING_APP_ID}"}}').encode(),
            request_format="legacy_json",
        ),
        ContractScenario(
            name="list_apps_legacy_json_out_of_range",
            method=PUBLIC_API_METHODS["listApps"],
            body=(b'{"start":2147483647,"num":1,"query":"","trs80":{"mediaTypes":[]}}'),
            request_format="legacy_json",
        ),
        ContractScenario(
            name="fetch_media_images_legacy_json_missing_id",
            method=PUBLIC_API_METHODS["fetchMediaImages"],
            body=(f'{{"appId":"{MISSING_APP_ID}"}}').encode(),
            request_format="legacy_json",
        ),
        ContractScenario(
            name="get_app_legacy_json_existing",
            method=PUBLIC_API_METHODS["getApp"],
            body=(f'{{"appId":"{FIXTURE_APP_ID}"}}').encode(),
            request_format="legacy_json",
            category=ScenarioCategory.SUCCESS,
        ),
        ContractScenario(
            name="list_apps_legacy_json_first_page",
            method=PUBLIC_API_METHODS["listApps"],
            body=(b'{"start":0,"num":2,"query":"","trs80":{"mediaTypes":[]}}'),
            request_format="legacy_json",
            category=ScenarioCategory.SUCCESS,
        ),
        ContractScenario(
            name="fetch_media_images_legacy_json_existing",
            method=PUBLIC_API_METHODS["fetchMediaImages"],
            body=(f'{{"appId":"{FIXTURE_APP_ID}"}}').encode(),
            request_format="legacy_json",
            category=ScenarioCategory.SUCCESS,
        ),
    )


def all_safe_scenarios() -> tuple[ContractScenario, ...]:
    scenarios = (
        *safe_baseline_scenarios(),
        *safe_success_scenarios(),
        *safe_boundary_scenarios(),
        *safe_malformed_scenarios(),
        *safe_legacy_json_scenarios(),
    )
    duplicate_names = [
        name
        for name in {scenario.name for scenario in scenarios}
        if sum(scenario.name == name for scenario in scenarios) > 1
    ]
    if duplicate_names:
        raise RuntimeError(f"Duplicate contract scenario names: {sorted(duplicate_names)}")

    unsafe = [scenario.name for scenario in scenarios if not _is_mutation_safe(scenario)]
    if unsafe:
        raise RuntimeError(f"Unsafe production contract scenarios: {unsafe}")
    return scenarios


def _is_mutation_safe(scenario: ContractScenario) -> bool:
    if not scenario.method.writes_state:
        return True
    try:
        request = api_pb.UploadSystemStateParams.FromString(scenario.body)
    except DecodeError:
        return True

    regions = request.state.memoryRegions
    if not regions:
        return False
    return any(
        region.start < 0
        or region.start >= 1_000_000
        or region.length >= 1_000_000
        or len(region.data) >= 1_000_000
        for region in regions
    )


def _snake_case(value: str) -> str:
    characters: list[str] = []
    for character in value:
        if character.isupper():
            characters.extend(("_", character.lower()))
        else:
            characters.append(character)
    return "".join(characters)

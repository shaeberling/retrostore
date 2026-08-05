"""Mutation-safe baseline requests for every public API method."""

from dataclasses import dataclass

from google.protobuf.message import Message

from retrostore.contracts import PUBLIC_API_METHODS, ApiMethodContract
from retrostore.generated import ApiProtos_pb2 as api_pb

MISSING_APP_ID = "__retrostore_contract_missing__"


@dataclass(frozen=True, slots=True)
class ContractScenario:
    name: str
    method: ApiMethodContract
    body: bytes
    request_format: str = "protobuf"


def _protobuf(name: str, method_name: str, request: Message) -> ContractScenario:
    return ContractScenario(
        name=name,
        method=PUBLIC_API_METHODS[method_name],
        body=request.SerializeToString(),
    )


def safe_baseline_scenarios() -> tuple[ContractScenario, ...]:
    """Return requests that cannot mutate production state.

    The legacy implementation considers an empty uploadState request valid. Its
    scenario therefore contains a memory region with a negative start address,
    which deterministically fails validation before token allocation.
    """

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
            body=(
                b'{"start":2147483647,"num":1,"query":"",'
                b'"trs80":{"mediaTypes":[]}}'
            ),
            request_format="legacy_json",
        ),
        ContractScenario(
            name="fetch_media_images_legacy_json_missing_id",
            method=PUBLIC_API_METHODS["fetchMediaImages"],
            body=(f'{{"appId":"{MISSING_APP_ID}"}}').encode(),
            request_format="legacy_json",
        ),
    )

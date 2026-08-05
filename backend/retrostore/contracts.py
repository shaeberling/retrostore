"""Machine-readable definition of the frozen public RetroStore API surface."""

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from google.protobuf.message import Message

from retrostore.generated import ApiProtos_pb2 as api_pb


class ResponseKind(StrEnum):
    PROTOBUF = "protobuf"
    RAW_BYTES = "raw_bytes"


@dataclass(frozen=True, slots=True)
class ApiMethodContract:
    name: str
    request_type: type[Message]
    response_kind: ResponseKind
    response_type: type[Message] | None = None
    accepts_legacy_json: bool = False
    writes_state: bool = False


_METHODS = (
    ApiMethodContract(
        "getApp",
        api_pb.GetAppParams,
        ResponseKind.PROTOBUF,
        api_pb.ApiResponseApps,
        accepts_legacy_json=True,
    ),
    ApiMethodContract(
        "listApps",
        api_pb.ListAppsParams,
        ResponseKind.PROTOBUF,
        api_pb.ApiResponseApps,
        accepts_legacy_json=True,
    ),
    ApiMethodContract(
        "listAppsNano",
        api_pb.ListAppsParams,
        ResponseKind.PROTOBUF,
        api_pb.ApiResponseAppsNano,
    ),
    ApiMethodContract(
        "fetchMediaImages",
        api_pb.FetchMediaImagesParams,
        ResponseKind.PROTOBUF,
        api_pb.ApiResponseMediaImages,
        accepts_legacy_json=True,
    ),
    ApiMethodContract(
        "fetchMediaImageRefs",
        api_pb.FetchMediaImageRefsParams,
        ResponseKind.PROTOBUF,
        api_pb.ApiResponseMediaImageRefs,
    ),
    ApiMethodContract(
        "fetchMediaImageRegion",
        api_pb.FetchMediaImageRegionParams,
        ResponseKind.RAW_BYTES,
    ),
    ApiMethodContract(
        "uploadState",
        api_pb.UploadSystemStateParams,
        ResponseKind.PROTOBUF,
        api_pb.ApiResponseUploadSystemState,
        writes_state=True,
    ),
    ApiMethodContract(
        "downloadState",
        api_pb.DownloadSystemStateParams,
        ResponseKind.PROTOBUF,
        api_pb.ApiResponseDownloadSystemState,
    ),
    ApiMethodContract(
        "downloadStateMemoryRegion",
        api_pb.DownloadSystemStateMemoryRegionParams,
        ResponseKind.RAW_BYTES,
    ),
)

PUBLIC_API_METHODS = MappingProxyType({method.name: method for method in _METHODS})

if len(PUBLIC_API_METHODS) != len(_METHODS):
    raise RuntimeError("Duplicate public API method name")

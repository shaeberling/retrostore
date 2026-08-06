"""Request parsing and legacy-compatible behavior for the nine public RPCs."""

import json
from collections.abc import Callable, Mapping
from typing import Any

from flask import Response
from google.protobuf.message import DecodeError, Message

from retrostore.api_compat.storage import CatalogEntry, CompatibilityStorage
from retrostore.generated import ApiProtos_pb2 as api_pb

ApiHandler = Callable[[bytes], Response]

_CONTENT_TYPE = "application/octet-stream"
_ALL_GOOD = "All good :-)"
_MAX_REGION_LENGTH = 10 << 18
_MAX_STATE_VALUE = 1_000_000
_MALFORMED_PROTOBUF_MESSAGE = (
    "While parsing a protocol message, the input ended unexpectedly in the middle of a field.  "
    "This could mean either that the input has been truncated or that an embedded message "
    "misreported its own length."
)
_NULL_POINTER_ERROR = (
    b"<html><head><title>Server Error</title></head><body>Request failed: Unexpected exception "
    b"from servlet: java.lang.NullPointerException</body></html>"
)
_NEGATIVE_START_ERROR = (
    b"<html><head><title>Server Error</title></head><body>Request failed: Unexpected exception "
    b"from servlet: java.lang.IndexOutOfBoundsException: Index -1 out of bounds for length "
    b"32</body></html>"
)


def build_handlers(storage: CompatibilityStorage) -> Mapping[str, ApiHandler]:
    """Build the complete handler map consumed by the Flask transport."""

    return CompatibilityApi(storage).handlers


class CompatibilityApi:
    """Legacy API behavior independent of Flask routing and persistence choice."""

    def __init__(self, storage: CompatibilityStorage) -> None:
        self._storage = storage
        self.handlers: Mapping[str, ApiHandler] = {
            "getApp": self.get_app,
            "listApps": self.list_apps,
            "listAppsNano": self.list_apps_nano,
            "fetchMediaImages": self.fetch_media_images,
            "fetchMediaImageRefs": self.fetch_media_image_refs,
            "fetchMediaImageRegion": self.fetch_media_image_region,
            "uploadState": self.upload_state,
            "downloadState": self.download_state,
            "downloadStateMemoryRegion": self.download_state_memory_region,
        }

    def get_app(self, body: bytes) -> Response:
        app_id = self._parse_get_app(body)
        response = api_pb.ApiResponseApps()
        if not app_id:
            return _protobuf(
                response,
                success=False,
                message="Invalid request, appId missing.",
            )

        entry = self._storage.get_catalog_entry(app_id)
        if entry is None:
            return _protobuf(response, success=False, message="App not found.")

        response.app.add().CopyFrom(entry.app)
        return _protobuf(response, success=True, message=_ALL_GOOD)

    def list_apps(self, body: bytes) -> Response:
        params = self._parse_list_apps(body, allow_legacy_json=True)
        response = api_pb.ApiResponseApps()
        result = self._filtered_catalog(params)
        if isinstance(result, str):
            return _protobuf(response, success=False, message=result)
        if result is None:
            return _server_error(_NEGATIVE_START_ERROR)

        entries, start, num = result
        for entry in entries[start : start + max(num, 0)]:
            response.app.add().CopyFrom(entry.app)
        return _protobuf(response, success=True, message=_ALL_GOOD)

    def list_apps_nano(self, body: bytes) -> Response:
        params = self._parse_list_apps(body, allow_legacy_json=False)
        response = api_pb.ApiResponseAppsNano()
        result = self._filtered_catalog(params)
        if isinstance(result, str):
            return _protobuf(response, success=False, message=result)
        if result is None:
            return _server_error(_NEGATIVE_START_ERROR)

        entries, start, num = result
        for entry in entries[start : start + max(num, 0)]:
            app = entry.app
            nano = response.app.add(
                id=app.id,
                name=app.name,
                version=app.version,
                release_year=app.release_year,
                author=app.author,
            )
            nano.ext_trs80.CopyFrom(app.ext_trs80)
        return _protobuf(response, success=True, message=_ALL_GOOD)

    def fetch_media_images(self, body: bytes) -> Response:
        params = self._parse_media_params(body, allow_legacy_json=True)
        if params is None:
            return _server_error(_NULL_POINTER_ERROR)
        return _protobuf_message(self._media_response(*params))

    def fetch_media_image_refs(self, body: bytes) -> Response:
        params = self._parse_media_params(body, allow_legacy_json=False)
        if params is None:
            return _server_error(_NULL_POINTER_ERROR)

        app_id, media_types = params
        media_response = self._media_response(app_id, media_types)
        response = api_pb.ApiResponseMediaImageRefs()
        if not media_response.success:
            return _protobuf(response, success=False, message=media_response.message)

        for image in media_response.mediaImage:
            if not image.data:
                continue
            response.mediaImageRef.add(
                type=image.type,
                filename=image.filename,
                token=f"{app_id}/{image.filename}",
                uploadTime=image.uploadTime,
                description=image.description,
                size=len(image.data),
            )
        return _protobuf(response, success=True, message=_ALL_GOOD)

    def fetch_media_image_region(self, body: bytes) -> Response:
        params = _parse_protobuf(api_pb.FetchMediaImageRegionParams, body)
        if params is None or not params.token:
            return _raw(b"")
        token_parts = params.token.split("/")
        if len(token_parts) != 2 or not all(token_parts):
            return _raw(b"")
        if params.start < 0 or params.length <= 0 or params.length > _MAX_REGION_LENGTH:
            return _raw(b"")

        app_id, filename = token_parts
        entry = self._storage.get_catalog_entry(app_id)
        if entry is None:
            return _raw(b"")

        image = next(
            (
                slot.image
                for slot in self._storage.get_media_slots(app_id)
                if slot.image.data and slot.image.filename == filename
            ),
            None,
        )
        if image is None:
            return _server_error(_NULL_POINTER_ERROR)

        return _raw(bytes(image.data[params.start : params.start + params.length]))

    def upload_state(self, body: bytes) -> Response:
        params = _parse_protobuf(api_pb.UploadSystemStateParams, body)
        response = api_pb.ApiResponseUploadSystemState()
        if params is None:
            return _protobuf(
                response,
                success=False,
                message=f"Cannot parse ProtoBuf params: {_MALFORMED_PROTOBUF_MESSAGE}",
            )
        if not self._state_is_valid(params.state):
            return _protobuf(response, success=False, message="Uploaded state is invalid")

        token = self._storage.save_state(self._normalized_state(params.state))
        response.token = token
        return _protobuf(response, success=True)

    def download_state(self, body: bytes) -> Response:
        params = _parse_protobuf(api_pb.DownloadSystemStateParams, body)
        response = api_pb.ApiResponseDownloadSystemState()
        if params is None:
            return _protobuf(
                response,
                success=False,
                message=f"Cannot parse ProtoBuf params: {_MALFORMED_PROTOBUF_MESSAGE}",
            )
        if params.token <= 0:
            return _protobuf(
                response,
                success=False,
                message="Illegal params. Ensure 'token' is > 0.",
            )

        state = self._storage.get_state(params.token)
        if state is None:
            return _protobuf(
                response,
                success=False,
                message=f"Cannot find system state with given token '{params.token}'",
            )
        response.success = True
        response.systemState.CopyFrom(state)
        if params.exclude_memory_region_data:
            for region in response.systemState.memoryRegions:
                region.data = b""
        return _protobuf_message(response)

    def download_state_memory_region(self, body: bytes) -> Response:
        params = _parse_protobuf(api_pb.DownloadSystemStateMemoryRegionParams, body)
        if (
            params is None
            or params.token <= 0
            or params.start <= 0
            or params.length <= 0
            or params.length > _MAX_REGION_LENGTH
        ):
            return _raw(b"")

        state = self._storage.get_state(params.token)
        if state is None:
            return _raw(b"")

        result = bytearray(params.length)
        request_end = params.start + params.length
        for region in state.memoryRegions:
            overlap_start = max(params.start, region.start)
            overlap_end = min(request_end, region.start + len(region.data))
            if overlap_start >= overlap_end:
                continue
            source_start = overlap_start - region.start
            target_start = overlap_start - params.start
            size = overlap_end - overlap_start
            result[target_start : target_start + size] = region.data[
                source_start : source_start + size
            ]
        return _raw(bytes(result))

    def _filtered_catalog(
        self, params: api_pb.ListAppsParams | None
    ) -> tuple[list[CatalogEntry], int, int] | str | None:
        if params is None:
            return "Cannot parse parameters."

        entries = sorted(self._storage.list_catalog_entries(), key=lambda entry: entry.app.name)
        if len(entries) - 1 < params.start:
            return "Parameter 'start' out of range"

        if params.query.strip():
            matching_ids = self._storage.search_app_ids(params.query)
            entries = [entry for entry in entries if entry.app.id in matching_ids]
        media_types = frozenset(params.trs80.media_types)
        if media_types:
            entries = [entry for entry in entries if entry.media_types & media_types]
        if params.start < 0:
            return None
        return entries, params.start, params.num

    def _media_response(
        self, app_id: str, media_types: frozenset[int]
    ) -> api_pb.ApiResponseMediaImages:
        response = api_pb.ApiResponseMediaImages()
        if not app_id:
            response.success = False
            response.message = "No appId given."
            return response
        if self._storage.get_catalog_entry(app_id) is None:
            response.success = False
            response.message = f"Cannot find app with ID '{app_id}'."
            return response

        for slot in self._storage.get_media_slots(app_id):
            if not media_types or slot.media_type in media_types:
                response.mediaImage.add().CopyFrom(slot.image)
        response.success = True
        response.message = _ALL_GOOD
        return response

    @staticmethod
    def _parse_get_app(body: bytes) -> str | None:
        params = _parse_protobuf(api_pb.GetAppParams, body)
        if params is not None:
            return params.app_id
        legacy = _parse_json_object(body)
        if legacy is None:
            return None
        value = legacy.get("appId")
        return value if isinstance(value, str) else None

    @staticmethod
    def _parse_list_apps(
        body: bytes, *, allow_legacy_json: bool
    ) -> api_pb.ListAppsParams | None:
        params = _parse_protobuf(api_pb.ListAppsParams, body)
        if params is not None:
            return params
        if not allow_legacy_json:
            return None

        legacy = _parse_json_object(body)
        if legacy is None:
            return None
        try:
            params = api_pb.ListAppsParams(
                start=int(legacy.get("start", 0)),
                num=int(legacy.get("num", 0)),
                query=str(legacy.get("query") or ""),
            )
            legacy_trs80 = legacy.get("trs80") or {}
            media_names = legacy_trs80.get("mediaTypes") or []
            enum_values = api_pb.MediaType.keys()
            params.trs80.media_types.extend(
                api_pb.MediaType.Value(name) if name in enum_values else api_pb.UNKNOWN
                for name in media_names
            )
            return params
        except (AttributeError, TypeError, ValueError):
            return None

    @staticmethod
    def _parse_media_params(
        body: bytes, *, allow_legacy_json: bool
    ) -> tuple[str, frozenset[int]] | None:
        message_type = (
            api_pb.FetchMediaImagesParams
            if allow_legacy_json
            else api_pb.FetchMediaImageRefsParams
        )
        params = _parse_protobuf(message_type, body)
        if params is not None:
            return params.app_id, frozenset(params.media_type)
        if not allow_legacy_json:
            return None

        legacy = _parse_json_object(body)
        if legacy is None:
            return None
        value = legacy.get("appId")
        return (value if isinstance(value, str) else ""), frozenset()

    @staticmethod
    def _state_is_valid(state: api_pb.SystemState) -> bool:
        return all(
            region.start >= 0
            and region.start < _MAX_STATE_VALUE
            and region.length < _MAX_STATE_VALUE
            and len(region.data) < _MAX_STATE_VALUE
            for region in state.memoryRegions
        )

    @staticmethod
    def _normalized_state(state: api_pb.SystemState) -> api_pb.SystemState:
        normalized = api_pb.SystemState()
        normalized.CopyFrom(state)
        for region in normalized.memoryRegions:
            region.length = len(region.data)
        return normalized


def _parse_protobuf[MessageT: Message](
    message_type: type[MessageT], body: bytes
) -> MessageT | None:
    message = message_type()
    try:
        message.ParseFromString(body)
    except DecodeError:
        return None
    return message


def _parse_json_object(body: bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _protobuf(protobuf_message: Message, *, success: bool, message: str = "") -> Response:
    protobuf_message.success = success
    protobuf_message.message = message
    return _protobuf_message(protobuf_message)


def _protobuf_message(message: Message) -> Response:
    return _binary_response(message.SerializeToString())


def _raw(body: bytes) -> Response:
    return _binary_response(body)


def _binary_response(body: bytes) -> Response:
    response = Response(body, status=200, content_type=_CONTENT_TYPE)
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


def _server_error(body: bytes) -> Response:
    return Response(body, status=500, content_type="text/html")

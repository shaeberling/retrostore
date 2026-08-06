"""Reviewed local fixture adapter for the representative compatibility corpus."""

import base64
import gzip
import hashlib
import json
from pathlib import Path

from retrostore.api_compat.storage import CatalogEntry, InMemoryCompatibilityStorage, MediaSlot
from retrostore.generated import ApiProtos_pb2 as api_pb

_FIXTURE_DIRECTORY = Path(__file__).with_name("fixtures")
_APP_FIXTURE = _FIXTURE_DIRECTORY / "representative_apps.json"
_MEDIA_FIXTURE = _FIXTURE_DIRECTORY / "representative_media.pb.gz.b64"
_FIXTURE_APP_ID = "259847aa-ce3a-48bb-a037-e392beb96b22"
_EXPECTED_MEDIA_RESPONSE_SIZE = 101_864
_EXPECTED_MEDIA_RESPONSE_SHA256 = (
    "773c39cabf958c7993e243cf1e05242ab4a061808afe9df107aa5eb0772d40e3"
)


def representative_storage() -> InMemoryCompatibilityStorage:
    """Load the 32-entry local projection used by the reviewed 45-scenario corpus."""

    responses = _load_app_responses()
    first_page = responses["list_apps_first_page"]
    fixture_app = responses["get_app_existing"].app[0]
    last_page = responses["list_apps_last_page_truncated"]

    catalog = [
        CatalogEntry(_copy_app(first_page.app[0]), frozenset({api_pb.COMMAND})),
        CatalogEntry(_copy_app(first_page.app[1]), frozenset({api_pb.COMMAND})),
    ]
    catalog.extend(
        CatalogEntry(
            api_pb.App(id=f"__local_fixture_{index:02d}", name=f"Fixture {index:02d}"),
        )
        for index in range(28)
    )
    catalog.extend(
        (
            CatalogEntry(_copy_app(fixture_app), frozenset({api_pb.DISK, api_pb.COMMAND})),
            CatalogEntry(_copy_app(last_page.app[0])),
        )
    )
    if len(catalog) != 32 or len({entry.app.id for entry in catalog}) != 32:
        raise RuntimeError("Representative catalog fixture must contain 32 unique apps")

    media_response = _load_media_response()
    slot_types = (
        api_pb.DISK,
        api_pb.DISK,
        api_pb.DISK,
        api_pb.DISK,
        api_pb.CASSETTE,
        api_pb.COMMAND,
        api_pb.BASIC,
    )
    media_slots = tuple(
        MediaSlot(media_type, _copy_media(image))
        for media_type, image in zip(slot_types, media_response.mediaImage, strict=True)
    )
    return InMemoryCompatibilityStorage(catalog, {_FIXTURE_APP_ID: media_slots})


def _load_app_responses() -> dict[str, api_pb.ApiResponseApps]:
    encoded = json.loads(_APP_FIXTURE.read_text())
    return {
        name: api_pb.ApiResponseApps.FromString(base64.b64decode(body))
        for name, body in encoded.items()
    }


def _load_media_response() -> api_pb.ApiResponseMediaImages:
    compressed = base64.b64decode(_MEDIA_FIXTURE.read_text())
    serialized = gzip.decompress(compressed)
    if len(serialized) != _EXPECTED_MEDIA_RESPONSE_SIZE:
        raise RuntimeError("Representative media response size does not match its baseline")
    if hashlib.sha256(serialized).hexdigest() != _EXPECTED_MEDIA_RESPONSE_SHA256:
        raise RuntimeError("Representative media response digest does not match its baseline")
    return api_pb.ApiResponseMediaImages.FromString(serialized)


def _copy_app(app: api_pb.App) -> api_pb.App:
    copy = api_pb.App()
    copy.CopyFrom(app)
    return copy


def _copy_media(image: api_pb.MediaImage) -> api_pb.MediaImage:
    copy = api_pb.MediaImage()
    copy.CopyFrom(image)
    return copy

import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from flask import Response

from retrostore.api.storage import DownloadApp, DownloadMedia, InMemoryApiDataStore
from retrostore.generated import ApiProtos_pb2 as api_pb
from retrostore.testing.flask_api import (
    create_archive_app,
    create_representative_app,
)
from services.api.app import PUBLIC_REDIRECTS, create_app, create_cloud_app
from tests.migration.catalog_mirror.test_archive import _write_archive
from tests.migration.catalog_mirror.test_catalog import _manifest
from tests.migration.catalog_mirror.test_persistence import _mirror


def test_liveness_is_independent_of_implementation_readiness() -> None:
    client = create_app({"TESTING": True}).test_client()

    assert client.get("/health").status_code == 200
    readiness = client.get("/readyz")
    assert readiness.status_code == 503
    assert len(readiness.get_json()["missing_methods"]) == 9


def test_unknown_method_preserves_legacy_error_shape() -> None:
    client = create_app({"TESTING": True}).test_client()

    response = client.post("/api/doesNotExist", data=b"")

    assert response.status_code == 400
    assert response.data == b"RPC method 'doesNotExist' not found."
    assert response.content_type.startswith("text/plain")


def test_known_but_unimplemented_method_fails_closed() -> None:
    client = create_app({"TESTING": True}).test_client()

    response = client.post("/api/getApp", data=b"")

    assert response.status_code == 503
    assert b"not implemented" in response.data


def test_injected_handler_receives_the_unmodified_body() -> None:
    received = []

    def handler(body: bytes) -> Response:
        received.append(body)
        return Response(b"protobuf", mimetype="application/octet-stream")

    client = create_app(
        {"TESTING": True, "RETROSTORE_API_HANDLERS": {"getApp": handler}}
    ).test_client()

    response = client.post("/api/getApp", data=b"\x0a\x03abc")

    assert response.status_code == 200
    assert response.data == b"protobuf"
    assert received == [b"\x0a\x03abc"]


def test_representative_candidate_has_all_handlers() -> None:
    client = create_representative_app({"TESTING": True}).test_client()

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.get_json() == {"ready": True, "missing_methods": []}


@pytest.mark.parametrize(
    ("path", "destination"),
    tuple(PUBLIC_REDIRECTS.items()),
)
@pytest.mark.parametrize("suffix", ("", "/"))
@pytest.mark.parametrize("method", ("get", "post"))
def test_public_redirects_are_exact_empty_302_responses(
    path: str, destination: str, suffix: str, method: str
) -> None:
    client = create_app({"TESTING": True}).test_client()

    response = getattr(client, method)(f"{path}{suffix}")

    assert response.status_code == 302
    assert response.headers["Location"] == destination
    assert response.content_type == "text/html"
    assert response.data == b""


def test_public_redirects_do_not_capture_longer_paths() -> None:
    client = create_app({"TESTING": True}).test_client()

    assert client.get("/community/invite").status_code == 404


def test_archive_candidate_loads_only_from_explicit_verified_path(tmp_path: Path) -> None:
    archive = tmp_path / "catalog.zip"
    _write_archive(archive)
    client = create_archive_app(archive, {"TESTING": True}).test_client()

    readiness = client.get("/readyz")
    response = client.post(
        "/api/getApp",
        data=api_pb.GetAppParams(app_id="app-1").SerializeToString(),
    )
    app_response = api_pb.ApiResponseApps.FromString(response.data)

    assert readiness.status_code == 200
    assert app_response.success is True
    assert app_response.app[0].name == "Armored Patrol"
    assert app_response.app[0].screenshot_url == ["https://legacy.example/shot-1"]

    screenshot = client.get("/assets/screenshots/shot-1")
    assert screenshot.status_code == 200
    assert screenshot.data == b"screenshot"
    assert screenshot.content_type == "image/png"
    assert screenshot.cache_control.max_age == 31_536_000
    assert screenshot.cache_control.immutable is True
    assert screenshot.headers["X-Content-Type-Options"] == "nosniff"
    assert screenshot.headers["Access-Control-Allow-Origin"] == "*"

    download = client.get("/downloadapp?appId=app-1")
    assert download.status_code == 200
    assert download.content_type == "application/zip"
    assert download.headers["Content-Disposition"] == ('attachment; filename="Armored_Patrol.zip"')
    assert "Access-Control-Allow-Origin" not in download.headers
    with zipfile.ZipFile(BytesIO(download.data)) as archive:
        assert sorted(archive.namelist()) == ["game.cmd", "game.dmk"]
        assert archive.read("game.dmk") == b"disk image"

    typed = client.get("/downloadapp?appId=app-1&type=DMK")
    assert typed.status_code == 200
    assert typed.content_type == "application/octet-stream"
    assert typed.data == b"disk image"
    assert typed.headers["Access-Control-Allow-Origin"] == "*"

    public_apps = client.get("/public/apps.json")
    assert public_apps.status_code == 200
    assert public_apps.content_type == "application/json"
    assert public_apps.get_json() == [
        {
            "author": "Jane Doe",
            "description": "Tank game",
            "downloadUrl": "/downloadapp?appId=app-1",
            "emulatorAppId": "app-1",
            "name": "Armored Patrol",
            "reportUrl": "/reportapp?appId=app-1",
            "screenshots": ["https://legacy.example/shot-1"],
            "version": "1.0",
        }
    ]


def test_download_app_preserves_error_text_and_media_tie_break() -> None:
    client = create_app(
        {
            "TESTING": True,
            "RETROSTORE_DOWNLOADS": {
                "app": DownloadApp(
                    name="Name, with.space",
                    media=(
                        DownloadMedia("1", "first.dsk", b"first"),
                        DownloadMedia("2", "second.dsk", b"second"),
                    ),
                )
            },
        }
    ).test_client()

    missing = client.get("/downloadapp")
    invalid = client.get("/downloadapp?appId=missing")
    typed = client.get("/downloadapp?appId=app&type=dsk")
    zipped = client.get("/downloadapp?appId=app")

    assert missing.status_code == 400
    assert missing.data == b"'appId' missing."
    assert missing.content_type == "text/plain;charset=iso-8859-1"
    assert invalid.data == b"Cannot find app with ID missing"
    assert typed.data == b"first"
    assert zipped.headers["Content-Disposition"] == ('attachment; filename="Name__with_space.zip"')


def test_new_screenshot_uses_the_immutable_candidate_route(tmp_path: Path) -> None:
    archive = tmp_path / "catalog.zip"
    manifest = _manifest()
    manifest["screenshots"][0]["legacy_serving_url"] = None  # type: ignore[index]
    _write_archive(archive, manifest=manifest)

    client = create_archive_app(
        archive,
        {
            "TESTING": True,
            "RETROSTORE_PUBLIC_ORIGIN": "https://preview.example.test/",
        },
    ).test_client()
    response = client.post(
        "/api/getApp",
        data=api_pb.GetAppParams(app_id="app-1").SerializeToString(),
    )

    app_response = api_pb.ApiResponseApps.FromString(response.data)
    assert app_response.app[0].screenshot_url == ["https://preview.example.test/s/shot-1"]
    assert client.get("/s/shot-1").data == b"screenshot"
    assert client.get("/public/apps.json").get_json()[0]["screenshots"] == [
        "https://preview.example.test/s/shot-1"
    ]


def test_candidate_rejects_a_public_origin_with_a_path(tmp_path: Path) -> None:
    archive = tmp_path / "catalog.zip"
    _write_archive(archive)

    with pytest.raises(RuntimeError, match=r"HTTP\(S\) origin"):
        create_archive_app(
            archive,
            {"RETROSTORE_PUBLIC_ORIGIN": "https://preview.example.test/path"},
        )


def test_cloud_candidate_fails_closed_without_explicit_resource_names() -> None:
    with pytest.raises(RuntimeError, match="Cloud catalog configuration is missing"):
        create_cloud_app({"TESTING": True})


def test_cloud_app_defers_catalog_reads_until_an_api_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mirror = _mirror()
    repository = _MirrorRepository(mirror)
    object_reader = _MirrorObjectReader(mirror.object_bytes)
    monkeypatch.setattr(
        "retrostore.catalog.create_google_catalog",
        lambda **kwargs: (repository, object_reader),
    )
    client = create_cloud_app(
        {
            "TESTING": True,
            "RETROSTORE_PROJECT": "trs-80",
            "RETROSTORE_CATALOG_DATABASE": "retrostore",
            "RETROSTORE_ASSETS_BUCKET": "trs-80-retrostore-assets",
            "RETROSTORE_STATE_STORAGE": InMemoryApiDataStore(),
        }
    ).test_client()

    assert repository.calls == []
    readiness = client.get("/readyz")
    assert repository.calls == []
    response = client.post(
        "/api/getApp",
        data=api_pb.GetAppParams(app_id="app-1").SerializeToString(),
    )
    app_response = api_pb.ApiResponseApps.FromString(response.data)

    assert readiness.status_code == 200
    assert app_response.success is True
    assert app_response.app[0].name == "Armored Patrol"
    assert repository.calls == ["get_app", "get_screenshots"]
    assert object_reader.reads == []


class _MirrorRepository:
    def __init__(self, mirror):
        self.mirror = mirror
        self.calls: list[str] = []

    def list_apps(self):
        self.calls.append("list_apps")
        return self.mirror.apps

    def get_app(self, app_id):
        self.calls.append("get_app")
        return next((app for app in self.mirror.apps if app.id == app_id), None)

    def get_media(self, media_ids, *, app_id):
        self.calls.append("get_media")
        return {media_id: self.mirror.media[media_id] for media_id in media_ids}

    def list_media(self):
        self.calls.append("list_media")
        return self.mirror.media

    def get_screenshots(self, screenshot_ids, *, app_id):
        self.calls.append("get_screenshots")
        return {
            screenshot_id: self.mirror.screenshots[screenshot_id]
            for screenshot_id in screenshot_ids
        }

    def list_screenshots(self):
        self.calls.append("list_screenshots")
        return self.mirror.screenshots

    def get_screenshot(self, screenshot_id):
        self.calls.append("get_screenshot")
        return self.mirror.screenshots.get(screenshot_id)


class _MirrorObjectReader:
    def __init__(self, objects):
        self.objects = objects
        self.reads: list[tuple[str, int, int | None]] = []

    def read(self, descriptor, start=0, length=None):
        self.reads.append((descriptor.path, start, length))
        body = self.objects[descriptor.path]
        return body[start:] if length is None else body[start : start + length]

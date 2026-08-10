"""Flask entry point for the public compatibility API candidate."""

import os
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from flask import Flask, Response, abort, jsonify, request

from retrostore.api_compat.service import build_handlers
from retrostore.api_compat.storage import CompatibilityStorage
from retrostore.contracts import PUBLIC_API_METHODS
from retrostore.observability import register_request_observability

ApiHandler = Callable[[bytes], Response]


@dataclass(frozen=True, slots=True)
class PublicScreenshot:
    filename: str
    content_type: str
    sha256: str
    body: bytes


@dataclass(frozen=True, slots=True)
class LegacyDownloadMedia:
    id: str
    filename: str
    body: bytes


@dataclass(frozen=True, slots=True)
class LegacyDownloadApp:
    name: str
    media: tuple[LegacyDownloadMedia, ...]


def create_app(config: Mapping[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        RETROSTORE_API_HANDLERS=None,
        RETROSTORE_API_STORAGE=None,
        RETROSTORE_OBSERVABLE_API_METHODS=frozenset(PUBLIC_API_METHODS),
        RETROSTORE_PROJECT=os.environ.get("RETROSTORE_PROJECT"),
        RETROSTORE_REQUEST_LOGGING=True,
        RETROSTORE_LEGACY_DOWNLOADS={},
        RETROSTORE_PUBLIC_WEBSITE_APPS=(),
        RETROSTORE_SCREENSHOTS={},
    )
    if config:
        app.config.from_mapping(config)

    register_request_observability(app, service="retrostore-api-compat")

    handlers = app.config["RETROSTORE_API_HANDLERS"]
    storage: CompatibilityStorage | None = app.config["RETROSTORE_API_STORAGE"]
    if handlers is None:
        handlers = {} if storage is None else build_handlers(storage)
    app.config["RETROSTORE_API_HANDLERS"] = handlers

    @app.get("/healthz")
    @app.get("/health")
    def health() -> tuple[dict[str, str], int]:
        return {"service": "retrostore-api-compat", "status": "alive"}, 200

    @app.get("/readyz")
    @app.get("/ready")
    def readiness() -> tuple[dict[str, object], int]:
        handlers = app.config["RETROSTORE_API_HANDLERS"]
        missing = sorted(set(PUBLIC_API_METHODS) - set(handlers))
        status = 200 if not missing else 503
        return {"ready": not missing, "missing_methods": missing}, status

    @app.route("/api/<method_name>", methods=["GET", "POST"])
    def api(method_name: str) -> Response:
        if method_name not in PUBLIC_API_METHODS:
            return Response(
                f"RPC method '{method_name}' not found.", status=400, mimetype="text/plain"
            )

        handlers: Mapping[str, ApiHandler] = app.config["RETROSTORE_API_HANDLERS"]
        handler = handlers.get(method_name)
        if handler is None:
            return Response(
                f"Compatibility API method '{method_name}' is not implemented.",
                status=503,
                mimetype="text/plain",
            )
        return handler(request.get_data(cache=False, as_text=False))

    @app.get("/s/<screenshot_id>")
    @app.get("/assets/screenshots/<screenshot_id>")
    def screenshot(screenshot_id: str) -> Response:
        screenshots: Mapping[str, PublicScreenshot] = app.config[
            "RETROSTORE_SCREENSHOTS"
        ]
        value = screenshots.get(screenshot_id)
        if value is None:
            abort(404)
        response = Response(value.body, mimetype=value.content_type)
        response.set_etag(value.sha256, weak=False)
        response.cache_control.public = True
        response.cache_control.max_age = 31_536_000
        response.cache_control.immutable = True
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response

    @app.get("/downloadapp")
    def legacy_download() -> Response:
        app_id = request.args.get("appId")
        if app_id is None:
            return _legacy_download_error("'appId' missing.")

        downloads: Mapping[str, LegacyDownloadApp] = app.config[
            "RETROSTORE_LEGACY_DOWNLOADS"
        ]
        value = downloads.get(app_id)
        if value is None:
            return _legacy_download_error(f"Cannot find app with ID {app_id}")

        requested_type = request.args.get("type")
        if requested_type is not None:
            suffix = f".{requested_type.casefold()}"
            selected = next(
                (
                    media
                    for media in value.media
                    if media.filename.casefold().endswith(suffix)
                ),
                None,
            )
            if selected is None and value.media:
                return _legacy_download_error(f"Cannot find app with ID {app_id}")
            body = b"" if selected is None else selected.body
            response = Response(body, content_type="application/octet-stream")
            response.headers["Access-Control-Allow-Origin"] = "*"
            return response

        output = BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for media in sorted(value.media, key=lambda item: item.filename):
                archive.writestr(media.filename, media.body)
        filename = _legacy_download_filename(value.name)
        response = Response(output.getvalue(), content_type="application/zip")
        response.headers["Content-Disposition"] = f'attachment; filename="{filename}.zip"'
        return response

    @app.get("/public/apps.json")
    def public_website_apps() -> Response:
        return jsonify(app.config["RETROSTORE_PUBLIC_WEBSITE_APPS"])

    return app


def create_representative_app(config: Mapping[str, Any] | None = None) -> Flask:
    """Create the local-only candidate backed by the reviewed representative fixture."""

    from retrostore.api_compat.representative import representative_storage

    candidate_config = {"RETROSTORE_API_STORAGE": representative_storage()}
    if config:
        candidate_config.update(config)
    return create_app(candidate_config)


def create_archive_app(
    archive_path: str | Path, config: Mapping[str, Any] | None = None
) -> Flask:
    """Create an explicitly configured candidate from a verified migration archive."""

    from retrostore.mirror import MirrorCompatibilityStorage, load_catalog_mirror_archive

    candidate_config: dict[str, Any] = {
        "RETROSTORE_PUBLIC_ORIGIN": "https://retrostore.org"
    }
    if config:
        candidate_config.update(config)
    public_origin = _public_origin(candidate_config["RETROSTORE_PUBLIC_ORIGIN"])
    mirror = load_catalog_mirror_archive(Path(archive_path))
    screenshots = _public_screenshots(mirror)
    downloads = _legacy_downloads(mirror)
    public_apps = _public_website_apps(mirror, public_origin)
    storage = MirrorCompatibilityStorage(
        mirror,
        screenshot_url=_screenshot_url_resolver(public_origin),
    )
    candidate_config.update(
        {
            "RETROSTORE_API_STORAGE": storage,
            "RETROSTORE_LEGACY_DOWNLOADS": downloads,
            "RETROSTORE_PUBLIC_WEBSITE_APPS": public_apps,
            "RETROSTORE_SCREENSHOTS": screenshots,
        }
    )
    return create_app(candidate_config)


def create_cloud_app(config: Mapping[str, Any] | None = None) -> Flask:
    """Create the deployable candidate from an active isolated cloud snapshot."""

    from retrostore.api_compat.google_cloud_state import google_state_storage
    from retrostore.mirror import MirrorCompatibilityStorage, load_active_catalog_mirror
    from retrostore.mirror.google_cloud import google_catalog_stores

    candidate_config: dict[str, Any] = {
        "RETROSTORE_PROJECT": os.environ.get("RETROSTORE_PROJECT"),
        "RETROSTORE_CATALOG_DATABASE": os.environ.get(
            "RETROSTORE_CATALOG_DATABASE"
        ),
        "RETROSTORE_ASSETS_BUCKET": os.environ.get("RETROSTORE_ASSETS_BUCKET"),
        "RETROSTORE_PUBLIC_ORIGIN": os.environ.get(
            "RETROSTORE_PUBLIC_ORIGIN", "https://retrostore.org"
        ),
        "RETROSTORE_CATALOG_SNAPSHOT_ID": os.environ.get(
            "RETROSTORE_CATALOG_SNAPSHOT_ID"
        ),
        "RETROSTORE_CATALOG_SNAPSHOT_MANIFEST_SHA256": os.environ.get(
            "RETROSTORE_CATALOG_SNAPSHOT_MANIFEST_SHA256"
        ),
        "RETROSTORE_STATE_DATABASE": os.environ.get("RETROSTORE_STATE_DATABASE"),
        "RETROSTORE_STATE_BUCKET": os.environ.get("RETROSTORE_STATE_BUCKET"),
        "RETROSTORE_STATE_STORAGE": None,
    }
    if config:
        candidate_config.update(config)

    required = (
        "RETROSTORE_PROJECT",
        "RETROSTORE_CATALOG_DATABASE",
        "RETROSTORE_ASSETS_BUCKET",
    )
    if candidate_config["RETROSTORE_STATE_STORAGE"] is None:
        required = (*required, "RETROSTORE_STATE_DATABASE", "RETROSTORE_STATE_BUCKET")
    missing = [name for name in required if not candidate_config.get(name)]
    if missing:
        raise RuntimeError(f"Cloud catalog configuration is missing: {', '.join(missing)}")

    pinned_snapshot_id = candidate_config.get("RETROSTORE_CATALOG_SNAPSHOT_ID")
    pinned_manifest_sha256 = candidate_config.get(
        "RETROSTORE_CATALOG_SNAPSHOT_MANIFEST_SHA256"
    )
    if bool(pinned_snapshot_id) != bool(pinned_manifest_sha256):
        raise RuntimeError(
            "Pinned catalog preview requires both snapshot ID and manifest SHA-256"
        )
    public_origin = _public_origin(candidate_config["RETROSTORE_PUBLIC_ORIGIN"])

    object_store, snapshot_store = google_catalog_stores(
        project=candidate_config["RETROSTORE_PROJECT"],
        database=candidate_config["RETROSTORE_CATALOG_DATABASE"],
        bucket=candidate_config["RETROSTORE_ASSETS_BUCKET"],
    )
    if pinned_snapshot_id:
        from retrostore.mirror import CatalogMirror

        mirror = CatalogMirror.from_dict(
            snapshot_store.load_snapshot_manifest(
                pinned_snapshot_id, pinned_manifest_sha256
            ),
            object_store,
        )
    else:
        mirror = load_active_catalog_mirror(object_store, snapshot_store)
    state_storage = candidate_config["RETROSTORE_STATE_STORAGE"]
    if state_storage is None:
        state_storage = google_state_storage(
            project=candidate_config["RETROSTORE_PROJECT"],
            database=candidate_config["RETROSTORE_STATE_DATABASE"],
            bucket=candidate_config["RETROSTORE_STATE_BUCKET"],
        )
    candidate_config["RETROSTORE_API_STORAGE"] = MirrorCompatibilityStorage(
        mirror,
        screenshot_url=_screenshot_url_resolver(public_origin),
        state_storage=state_storage,
    )
    candidate_config["RETROSTORE_LEGACY_DOWNLOADS"] = _legacy_downloads(mirror)
    candidate_config["RETROSTORE_PUBLIC_WEBSITE_APPS"] = _public_website_apps(
        mirror, public_origin
    )
    candidate_config["RETROSTORE_SCREENSHOTS"] = _public_screenshots(mirror)
    return create_app(candidate_config)


def _screenshot_url_resolver(public_origin: str) -> Callable[[Any], str]:
    def resolve(screenshot: Any) -> str:
        return screenshot.legacy_serving_url or (
            f"{public_origin}/s/{quote(screenshot.id, safe='')}"
        )

    return resolve


def _public_origin(value: object) -> str:
    if not isinstance(value, str):
        raise RuntimeError("RetroStore public origin must be an absolute HTTP(S) URL")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError("RetroStore public origin must be an absolute HTTP(S) origin")
    return f"{parsed.scheme}://{parsed.netloc}"


def _public_screenshots(mirror: Any) -> Mapping[str, PublicScreenshot]:
    return {
        screenshot.id: PublicScreenshot(
            filename=screenshot.filename,
            content_type=screenshot.content_type or "application/octet-stream",
            sha256=screenshot.object.sha256,
            body=mirror.object_bytes[screenshot.object.path],
        )
        for screenshot in mirror.screenshots.values()
    }


def _legacy_downloads(mirror: Any) -> Mapping[str, LegacyDownloadApp]:
    media_by_app: dict[str, list[LegacyDownloadMedia]] = {}
    for media in mirror.media.values():
        _validate_zip_filename(media.filename)
        media_by_app.setdefault(media.app_id, []).append(
            LegacyDownloadMedia(
                id=media.id,
                filename=media.filename,
                body=mirror.object_bytes[media.object.path],
            )
        )
    result = {}
    for app in mirror.apps:
        _legacy_download_filename(app.name)
        result[app.id] = LegacyDownloadApp(
            name=app.name,
            media=tuple(
                sorted(media_by_app.get(app.id, ()), key=_legacy_media_sort_key)
            ),
        )
    return result


def _public_website_apps(
    mirror: Any, public_origin: str
) -> tuple[dict[str, object], ...]:
    media_by_app: dict[str, list[Any]] = {}
    for media in mirror.media.values():
        media_by_app.setdefault(media.app_id, []).append(media)

    screenshots = mirror.screenshots
    result: list[dict[str, object]] = []
    for app in mirror.apps:
        item: dict[str, object] = {
            "name": app.name,
            "version": app.version,
            "author": app.author_name if app.author_id is not None else "Unknown author",
            "description": app.description,
            "screenshots": [
                screenshot.legacy_serving_url
                or f"{public_origin}/s/{quote(screenshot.id, safe='')}"
                for screenshot_id in app.screenshot_ids
                for screenshot in (screenshots[screenshot_id],)
            ],
            "reportUrl": f"/reportapp?appId={app.id}",
            "downloadUrl": f"/downloadapp?appId={app.id}",
        }
        if any(
            media.filename.casefold().endswith(".dmk")
            for media in media_by_app.get(app.id, ())
        ):
            item["emulatorAppId"] = app.id
        result.append(item)
    return tuple(sorted(result, key=lambda item: str(item["name"])))


def _legacy_download_error(message: str) -> Response:
    response = Response(message.encode("iso-8859-1"), status=400)
    response.headers["Content-Type"] = "text/plain;charset=iso-8859-1"
    return response


def _legacy_download_filename(app_name: str) -> str:
    value = app_name.replace(" ", "_").replace(".", "_").replace(",", "_")
    if not value or any(character in value for character in ('"', "\r", "\n")):
        raise ValueError("App name cannot be represented as a legacy download filename")
    return value


def _validate_zip_filename(filename: str) -> None:
    parts = filename.split("/")
    if (
        not filename
        or filename.startswith("/")
        or "\\" in filename
        or "\0" in filename
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ValueError("Media filename is unsafe for a legacy download archive")


def _legacy_media_sort_key(media: LegacyDownloadMedia) -> tuple[int, int | str]:
    try:
        return (0, int(media.id))
    except ValueError:
        return (1, media.id)


app = create_app()

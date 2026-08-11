"""Flask entry point for the public RetroStore API service."""

import os
import zipfile
from collections.abc import Callable, Mapping
from io import BytesIO
from typing import Any
from urllib.parse import urlsplit

from flask import Flask, Response, abort, jsonify, request

from retrostore.api.service import build_handlers
from retrostore.api.storage import (
    ApiDataStore,
    DownloadApp,
    PublicCatalog,
    PublicScreenshot,
)
from retrostore.contracts import PUBLIC_API_METHODS
from retrostore.observability import register_request_observability

ApiHandler = Callable[[bytes], Response]

PUBLIC_REDIRECTS = {
    "/community": "https://discord.gg/7sZTgHy",
    "/rsc": "https://github.com/apuder/RetroStoreCard",
    "/app": "https://play.google.com/store/apps/details?id=org.puder.trs80",
}


def create_app(config: Mapping[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        RETROSTORE_API_HANDLERS=None,
        RETROSTORE_API_STORAGE=None,
        RETROSTORE_OBSERVABLE_API_METHODS=frozenset(PUBLIC_API_METHODS),
        RETROSTORE_PROJECT=os.environ.get("RETROSTORE_PROJECT"),
        RETROSTORE_REQUEST_LOGGING=True,
        RETROSTORE_PUBLIC_CATALOG=None,
        RETROSTORE_DOWNLOADS={},
        RETROSTORE_PUBLIC_WEBSITE_APPS=(),
        RETROSTORE_SCREENSHOTS={},
    )
    if config:
        app.config.from_mapping(config)

    register_request_observability(app, service="retrostore-api")

    handlers = app.config["RETROSTORE_API_HANDLERS"]
    storage: ApiDataStore | None = app.config["RETROSTORE_API_STORAGE"]
    if handlers is None:
        handlers = {} if storage is None else build_handlers(storage)
    app.config["RETROSTORE_API_HANDLERS"] = handlers

    @app.get("/healthz")
    @app.get("/health")
    def health() -> tuple[dict[str, str], int]:
        return {"service": "retrostore-api", "status": "alive"}, 200

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
                f"Public API method '{method_name}' is not implemented.",
                status=503,
                mimetype="text/plain",
            )
        return handler(request.get_data(cache=False, as_text=False))

    @app.get("/s/<screenshot_id>")
    @app.get("/assets/screenshots/<screenshot_id>")
    def screenshot(screenshot_id: str) -> Response:
        public_catalog: PublicCatalog | None = app.config["RETROSTORE_PUBLIC_CATALOG"]
        if public_catalog is not None:
            value = public_catalog.get_screenshot(screenshot_id)
        else:
            screenshots: Mapping[str, PublicScreenshot] = app.config["RETROSTORE_SCREENSHOTS"]
            value = screenshots.get(screenshot_id)
        if value is None:
            abort(404)
        response = Response(value.read_body(), mimetype=value.content_type)
        response.set_etag(value.sha256, weak=False)
        response.cache_control.public = True
        response.cache_control.max_age = 31_536_000
        response.cache_control.immutable = True
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response

    @app.get("/downloadapp")
    def download_app() -> Response:
        app_id = request.args.get("appId")
        if app_id is None:
            return _download_error("'appId' missing.")

        public_catalog: PublicCatalog | None = app.config["RETROSTORE_PUBLIC_CATALOG"]
        if public_catalog is not None:
            value = public_catalog.get_download(app_id)
        else:
            downloads: Mapping[str, DownloadApp] = app.config["RETROSTORE_DOWNLOADS"]
            value = downloads.get(app_id)
        if value is None:
            return _download_error(f"Cannot find app with ID {app_id}")

        requested_type = request.args.get("type")
        if requested_type is not None:
            suffix = f".{requested_type.casefold()}"
            selected = next(
                (media for media in value.media if media.filename.casefold().endswith(suffix)),
                None,
            )
            if selected is None and value.media:
                return _download_error(f"Cannot find app with ID {app_id}")
            body = b"" if selected is None else selected.read_body()
            response = Response(body, content_type="application/octet-stream")
            response.headers["Access-Control-Allow-Origin"] = "*"
            return response

        output = BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for media in sorted(value.media, key=lambda item: item.filename):
                archive.writestr(media.filename, media.read_body())
        filename = _download_filename(value.name)
        response = Response(output.getvalue(), content_type="application/zip")
        response.headers["Content-Disposition"] = f'attachment; filename="{filename}.zip"'
        return response

    @app.get("/public/apps.json")
    def public_website_apps() -> Response:
        public_catalog: PublicCatalog | None = app.config["RETROSTORE_PUBLIC_CATALOG"]
        if public_catalog is not None:
            return jsonify(public_catalog.list_website_apps())
        return jsonify(app.config["RETROSTORE_PUBLIC_WEBSITE_APPS"])

    def public_redirect(destination: str) -> Response:
        return Response(
            status=302,
            content_type="text/html",
            headers={"Location": destination},
        )

    for redirect_path, destination in PUBLIC_REDIRECTS.items():
        app.add_url_rule(
            redirect_path,
            endpoint=f"redirect_{redirect_path.removeprefix('/')}",
            view_func=lambda destination=destination: public_redirect(destination),
            methods=["GET", "POST"],
            strict_slashes=False,
        )

    return app


def create_cloud_app(config: Mapping[str, Any] | None = None) -> Flask:
    """Create the deployable API backed by Firestore and Cloud Storage."""

    from retrostore.api.cloud_data_store import GoogleCloudApiDataStore
    from retrostore.api.google_cloud_state import google_state_storage
    from retrostore.catalog import create_google_catalog

    candidate_config: dict[str, Any] = {
        "RETROSTORE_PROJECT": os.environ.get("RETROSTORE_PROJECT"),
        "RETROSTORE_CATALOG_DATABASE": os.environ.get("RETROSTORE_CATALOG_DATABASE"),
        "RETROSTORE_ASSETS_BUCKET": os.environ.get("RETROSTORE_ASSETS_BUCKET"),
        "RETROSTORE_PUBLIC_ORIGIN": os.environ.get(
            "RETROSTORE_PUBLIC_ORIGIN", "https://retrostore.org"
        ),
        "RETROSTORE_STATE_DATABASE": os.environ.get("RETROSTORE_STATE_DATABASE"),
        "RETROSTORE_STATE_BUCKET": os.environ.get("RETROSTORE_STATE_BUCKET"),
        "RETROSTORE_API_STORAGE": None,
        "RETROSTORE_PUBLIC_CATALOG": None,
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

    public_origin = _public_origin(candidate_config["RETROSTORE_PUBLIC_ORIGIN"])
    state_storage = candidate_config["RETROSTORE_STATE_STORAGE"]
    if state_storage is None:
        state_storage = google_state_storage(
            project=candidate_config["RETROSTORE_PROJECT"],
            database=candidate_config["RETROSTORE_STATE_DATABASE"],
            bucket=candidate_config["RETROSTORE_STATE_BUCKET"],
        )
    if candidate_config["RETROSTORE_API_STORAGE"] is None:
        repository, object_reader = create_google_catalog(
            project=candidate_config["RETROSTORE_PROJECT"],
            database=candidate_config["RETROSTORE_CATALOG_DATABASE"],
            bucket=candidate_config["RETROSTORE_ASSETS_BUCKET"],
        )
        storage = GoogleCloudApiDataStore(
            repository,
            object_reader,
            state_storage,
            public_origin=public_origin,
        )
        candidate_config["RETROSTORE_API_STORAGE"] = storage
        candidate_config["RETROSTORE_PUBLIC_CATALOG"] = storage
    return create_app(candidate_config)


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


def _download_error(message: str) -> Response:
    response = Response(message.encode("iso-8859-1"), status=400)
    response.headers["Content-Type"] = "text/plain;charset=iso-8859-1"
    return response


def _download_filename(app_name: str) -> str:
    value = app_name.replace(" ", "_").replace(".", "_").replace(",", "_")
    if not value or any(character in value for character in ('"', "\r", "\n")):
        raise ValueError("App name cannot be represented as a download filename")
    return value


app = create_app()

"""Flask entry point for the public compatibility API candidate."""

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from flask import Flask, Response, abort, request

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


def create_app(config: Mapping[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        RETROSTORE_API_HANDLERS=None,
        RETROSTORE_API_STORAGE=None,
        RETROSTORE_PROJECT=os.environ.get("RETROSTORE_PROJECT"),
        RETROSTORE_REQUEST_LOGGING=True,
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
    storage = MirrorCompatibilityStorage(
        mirror,
        screenshot_url=_screenshot_url_resolver(public_origin),
    )
    candidate_config.update(
        {
            "RETROSTORE_API_STORAGE": storage,
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


app = create_app()

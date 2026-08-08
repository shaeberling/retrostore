"""Flask entry point for the public compatibility API candidate."""

import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from flask import Flask, Response, request

from retrostore.api_compat.firmware import (
    EmptyFirmwareStorage,
    FirmwareStorage,
    MirrorFirmwareStorage,
    firmware_response,
)
from retrostore.api_compat.service import build_handlers
from retrostore.api_compat.storage import CompatibilityStorage
from retrostore.contracts import PUBLIC_API_METHODS

ApiHandler = Callable[[bytes], Response]


def create_app(config: Mapping[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        RETROSTORE_API_HANDLERS=None,
        RETROSTORE_API_STORAGE=None,
        RETROSTORE_FIRMWARE_STORAGE=None,
    )
    if config:
        app.config.from_mapping(config)

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
        firmware_ready = app.config["RETROSTORE_FIRMWARE_STORAGE"] is not None
        ready = not missing and firmware_ready
        return {
            "ready": ready,
            "missing_methods": missing,
            "firmware": firmware_ready,
        }, 200 if ready else 503

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

    @app.route("/card/", defaults={"firmware_path": ""}, methods=["GET", "POST"])
    @app.route("/card/<path:firmware_path>", methods=["GET", "POST"])
    def card_firmware(firmware_path: str) -> Response:
        return _firmware_response("card", firmware_path)

    @app.route("/trs-io/", defaults={"firmware_path": ""}, methods=["GET", "POST"])
    @app.route("/trs-io/<path:firmware_path>", methods=["GET", "POST"])
    def trs_io_firmware(firmware_path: str) -> Response:
        return _firmware_response("trs-io", firmware_path)

    def _firmware_response(product: str, firmware_path: str) -> Response:
        storage: FirmwareStorage | None = app.config["RETROSTORE_FIRMWARE_STORAGE"]
        if storage is None:
            return Response(
                "Firmware compatibility storage is not configured.",
                status=503,
                content_type="text/plain",
            )
        return firmware_response(storage, product=product, request_path=firmware_path)

    return app


def create_representative_app(config: Mapping[str, Any] | None = None) -> Flask:
    """Create the local-only candidate backed by the reviewed representative fixture."""

    from retrostore.api_compat.representative import representative_storage

    candidate_config = {
        "RETROSTORE_API_STORAGE": representative_storage(),
        "RETROSTORE_FIRMWARE_STORAGE": EmptyFirmwareStorage(),
    }
    if config:
        candidate_config.update(config)
    return create_app(candidate_config)


def create_archive_app(
    archive_path: str | Path, config: Mapping[str, Any] | None = None
) -> Flask:
    """Create an explicitly configured candidate from a verified migration archive."""

    from retrostore.mirror import MirrorCompatibilityStorage, load_catalog_mirror_archive

    mirror = load_catalog_mirror_archive(Path(archive_path))
    storage = MirrorCompatibilityStorage(
        mirror,
        screenshot_url=lambda screenshot: screenshot.legacy_serving_url or "",
    )
    candidate_config = {
        "RETROSTORE_API_STORAGE": storage,
        "RETROSTORE_FIRMWARE_STORAGE": EmptyFirmwareStorage(),
    }
    if config:
        candidate_config.update(config)
    return create_app(candidate_config)


def create_cloud_app(config: Mapping[str, Any] | None = None) -> Flask:
    """Create the deployable candidate from an active isolated cloud snapshot."""

    from retrostore.api_compat.google_cloud_state import google_state_storage
    from retrostore.firmware_mirror import load_active_firmware_mirror
    from retrostore.firmware_mirror.google_cloud import google_firmware_stores
    from retrostore.mirror import MirrorCompatibilityStorage, load_active_catalog_mirror
    from retrostore.mirror.google_cloud import google_catalog_stores

    candidate_config: dict[str, Any] = {
        "RETROSTORE_PROJECT": os.environ.get("RETROSTORE_PROJECT"),
        "RETROSTORE_CATALOG_DATABASE": os.environ.get(
            "RETROSTORE_CATALOG_DATABASE"
        ),
        "RETROSTORE_ASSETS_BUCKET": os.environ.get("RETROSTORE_ASSETS_BUCKET"),
        "RETROSTORE_STATE_DATABASE": os.environ.get("RETROSTORE_STATE_DATABASE"),
        "RETROSTORE_STATE_BUCKET": os.environ.get("RETROSTORE_STATE_BUCKET"),
        "RETROSTORE_STATE_STORAGE": None,
        "RETROSTORE_FIRMWARE_STORAGE": None,
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

    object_store, snapshot_store = google_catalog_stores(
        project=candidate_config["RETROSTORE_PROJECT"],
        database=candidate_config["RETROSTORE_CATALOG_DATABASE"],
        bucket=candidate_config["RETROSTORE_ASSETS_BUCKET"],
    )
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
        screenshot_url=lambda screenshot: screenshot.legacy_serving_url or "",
        state_storage=state_storage,
    )
    if candidate_config["RETROSTORE_FIRMWARE_STORAGE"] is None:
        firmware_objects, firmware_snapshots = google_firmware_stores(
            project=candidate_config["RETROSTORE_PROJECT"],
            database=candidate_config["RETROSTORE_CATALOG_DATABASE"],
            bucket=candidate_config["RETROSTORE_ASSETS_BUCKET"],
        )
        candidate_config["RETROSTORE_FIRMWARE_STORAGE"] = MirrorFirmwareStorage(
            load_active_firmware_mirror(firmware_objects, firmware_snapshots)
        )
    return create_app(candidate_config)


app = create_app()

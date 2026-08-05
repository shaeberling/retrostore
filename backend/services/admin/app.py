"""Flask entry point for the server-rendered administration candidate."""

from collections.abc import Mapping
from typing import Any

from flask import Flask, render_template


def create_app(config: Mapping[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(ADMIN_PERSISTENCE_READY=False, ADMIN_AUTH_READY=False)
    if config:
        app.config.from_mapping(config)

    @app.get("/healthz")
    def health() -> tuple[dict[str, str], int]:
        return {"service": "retrostore-admin", "status": "alive"}, 200

    @app.get("/readyz")
    def readiness() -> tuple[dict[str, object], int]:
        checks = {
            "authentication": bool(app.config["ADMIN_AUTH_READY"]),
            "persistence": bool(app.config["ADMIN_PERSISTENCE_READY"]),
        }
        ready = all(checks.values())
        return {"ready": ready, "checks": checks}, 200 if ready else 503

    @app.get("/admin")
    def admin_index() -> str:
        return render_template("admin/index.html")

    return app


app = create_app()

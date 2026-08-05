"""Flask entry point for the public compatibility API candidate."""

from collections.abc import Callable, Mapping
from typing import Any

from flask import Flask, Response, request

from retrostore.contracts import PUBLIC_API_METHODS

ApiHandler = Callable[[bytes], Response]


def create_app(config: Mapping[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(RETROSTORE_API_HANDLERS={})
    if config:
        app.config.from_mapping(config)

    @app.get("/healthz")
    def health() -> tuple[dict[str, str], int]:
        return {"service": "retrostore-api-compat", "status": "alive"}, 200

    @app.get("/readyz")
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

    return app


app = create_app()

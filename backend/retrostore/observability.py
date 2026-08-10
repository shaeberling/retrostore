"""Privacy-safe structured request events for Cloud Run services."""

from __future__ import annotations

import json
import re
import sys
import time
from typing import Any

from flask import Flask, Response, g, request

_TRACE_ID = re.compile(r"^[0-9a-fA-F]{32}$")
_START_ATTRIBUTE = "_retrostore_request_started_ns"


def register_request_observability(app: Flask, *, service: str) -> None:
    """Emit one bounded JSON event per response without URLs or request data."""

    @app.before_request
    def start_request_observation() -> None:
        setattr(g, _START_ATTRIBUTE, time.perf_counter_ns())

    @app.after_request
    def emit_request_observation(response: Response) -> Response:
        if not app.config.get("RETROSTORE_REQUEST_LOGGING", True):
            return response

        started_ns = getattr(g, _START_ATTRIBUTE, time.perf_counter_ns())
        duration_seconds = max(0.0, (time.perf_counter_ns() - started_ns) / 1_000_000_000)
        endpoint = request.endpoint or "unmatched"
        event: dict[str, Any] = {
            "event": "http_request",
            "service": service,
            "endpoint": endpoint,
            "severity": "ERROR" if response.status_code >= 500 else "INFO",
            "httpRequest": {
                "requestMethod": request.method,
                "status": response.status_code,
                "latency": f"{duration_seconds:.6f}s",
            },
        }
        if request.content_length is not None:
            event["httpRequest"]["requestSize"] = str(request.content_length)
        response_size = response.calculate_content_length()
        if response_size is not None:
            event["httpRequest"]["responseSize"] = str(response_size)

        if endpoint == "api":
            method_name = (request.view_args or {}).get("method_name")
            observable_methods = app.config.get("RETROSTORE_OBSERVABLE_API_METHODS", ())
            if isinstance(method_name, str):
                event["api_method"] = (
                    method_name if method_name in observable_methods else "unknown"
                )

        project = app.config.get("RETROSTORE_PROJECT")
        trace_id = _cloud_trace_id(request.headers.get("X-Cloud-Trace-Context"))
        if isinstance(project, str) and project and trace_id:
            event["logging.googleapis.com/trace"] = f"projects/{project}/traces/{trace_id}"

        emit_structured_event(event)
        return response


def _cloud_trace_id(header: str | None) -> str | None:
    if not header:
        return None
    trace_id = header.split("/", 1)[0]
    return trace_id.lower() if _TRACE_ID.fullmatch(trace_id) else None


def emit_structured_event(event: dict[str, Any]) -> None:
    """Write one JSON object for Cloud Logging structured-payload detection."""

    sys.stdout.write(json.dumps(event, separators=(",", ":"), sort_keys=True) + "\n")
    sys.stdout.flush()

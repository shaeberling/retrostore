"""Render the approved candidate-only Google Cloud URL map."""

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from retrostore.contracts import PUBLIC_API_METHODS

_PROJECT = "trs-80"
_URL_MAP_NAME = "retrostore-next"
_API_BACKEND = "retrostore-api-next"
_ADMIN_BACKEND = "retrostore-admin-next"
_APP_ENGINE_BACKEND = "retrostore-appengine-default"
_STATIC_BACKEND = "retrostore-public-static"


def render_candidate_url_map(routes: Mapping[str, Any]) -> dict[str, Any]:
    """Compile exact checked-in route groups into an importable URL map."""
    if routes.get("schema_version") != 1 or routes.get("project") != _PROJECT:
        raise ValueError("Front-door route plan identity is invalid")
    candidate = routes["candidate_maps"]["parallel_candidate"]
    admin = routes["candidate_maps"]["admin_candidate"]
    if candidate.get("hostname") != "next.retrostore.org":
        raise ValueError("Parallel candidate hostname is not approved")
    if admin.get("hostname") != "admin-next.retrostore.org":
        raise ValueError("Admin candidate hostname is not approved")

    groups = {group["id"]: group for group in routes["route_groups"]}
    if len(groups) != len(routes["route_groups"]):
        raise ValueError("Route group IDs are not unique")
    api_paths: set[str] = set()
    static_paths: set[str] = set()
    claimed_paths: set[str] = set()
    for group_id in candidate["route_group_ids"]:
        group = groups[group_id]
        backend = group["future_backend"]
        target = static_paths if backend == "static_backend_bucket" else api_paths
        if backend not in {"static_backend_bucket", "cloud_run_api"}:
            raise ValueError(f"Candidate route group {group_id} has an unsafe backend")
        for path in group["paths"]:
            rendered = _render_path(path)
            if rendered in claimed_paths:
                raise ValueError(f"Candidate path appears more than once: {rendered}")
            claimed_paths.add(rendered)
            target.add(rendered)

    expected_api_methods = {f"/api/{method}" for method in PUBLIC_API_METHODS}
    if not expected_api_methods <= api_paths:
        raise ValueError("Candidate URL map omits a frozen public API method")
    if "/api/*" in api_paths:
        raise ValueError("Candidate URL map cannot claim unknown API methods")
    if len(static_paths) != 79 or "/" not in static_paths:
        raise ValueError("Candidate URL map static closure changed")

    api_service = _backend_service(_API_BACKEND)
    admin_service = _backend_service(_ADMIN_BACKEND)
    app_engine_service = _backend_service(_APP_ENGINE_BACKEND)
    static_service = _backend_bucket(_STATIC_BACKEND)
    return {
        "name": _URL_MAP_NAME,
        "description": (
            "Candidate-only RetroStore map; retrostore.org production remains unchanged"
        ),
        "defaultService": app_engine_service,
        "hostRules": [
            {
                "hosts": [candidate["hostname"]],
                "pathMatcher": "parallel-candidate",
            },
            {
                "hosts": [admin["hostname"]],
                "pathMatcher": "admin-candidate",
            },
        ],
        "pathMatchers": [
            {
                "name": "parallel-candidate",
                "defaultService": app_engine_service,
                "pathRules": [
                    {"paths": sorted(api_paths), "service": api_service},
                    {"paths": sorted(static_paths), "service": static_service},
                ],
            },
            {
                "name": "admin-candidate",
                "defaultService": admin_service,
            },
        ],
        "tests": [
            {
                "host": "next.retrostore.org",
                "path": "/api/listApps",
                "service": api_service,
            },
            {
                "host": "next.retrostore.org",
                "path": "/",
                "service": static_service,
            },
            {
                "host": "next.retrostore.org",
                "path": "/api/unknown",
                "service": app_engine_service,
            },
            {
                "host": "next.retrostore.org",
                "path": "/card",
                "service": app_engine_service,
            },
            {
                "host": "admin-next.retrostore.org",
                "path": "/",
                "service": admin_service,
            },
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--routes", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        raise FileExistsError(f"URL-map output already exists: {args.output}")
    routes = json.loads(args.routes.read_text())
    rendered = render_candidate_url_map(routes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(rendered, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "applied": False,
                "host_count": len(rendered["hostRules"]),
                "name": rendered["name"],
                "path_count": sum(
                    len(rule["paths"])
                    for matcher in rendered["pathMatchers"]
                    for rule in matcher.get("pathRules", [])
                ),
                "production_changed": False,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


def _render_path(path: Mapping[str, Any]) -> str:
    kind = path.get("kind")
    value = path.get("value")
    if kind == "exact" and isinstance(value, str) and value.startswith("/"):
        return value
    if kind == "prefix" and isinstance(value, str) and value.startswith("/"):
        return f"{value}*"
    raise ValueError(f"Unsupported candidate route: {path!r}")


def _backend_service(name: str) -> str:
    return (
        f"https://www.googleapis.com/compute/v1/projects/{_PROJECT}/global/backendServices/{name}"
    )


def _backend_bucket(name: str) -> str:
    return f"https://www.googleapis.com/compute/v1/projects/{_PROJECT}/global/backendBuckets/{name}"


if __name__ == "__main__":
    raise SystemExit(main())

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from retrostore.contract.front_door_fallbacks import (
    FALLBACK_SCENARIOS,
    compare_front_door_fallback_clients,
)


def _client(*, changed_path: str | None = None) -> httpx.Client:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == changed_path:
            return httpx.Response(502, content=b"changed")
        if request.url.path.startswith(("/public/", "/gfx/")):
            return httpx.Response(
                404,
                headers={"Content-Type": "text/html; charset=utf-8"},
                content=b"not found",
            )
        if request.url.path.startswith("/favicon/"):
            return httpx.Response(404, headers={"Content-Type": "text/plain"})
        if request.url.path.startswith("/api/"):
            return httpx.Response(
                400,
                headers={"Content-Type": "text/plain"},
                content=b"unknown method",
            )
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            content=(
                b'<meta http-equiv="refresh" content="0; url=/_ah/conflogin?continue=example">'
            ),
        )

    return httpx.Client(
        transport=httpx.MockTransport(handle),
        base_url="https://example.test",
        follow_redirects=False,
    )


def test_front_door_fallback_comparison_matches_and_sanitizes_login_body() -> None:
    with _client() as reference, _client() as candidate:
        report = compare_front_door_fallback_clients(
            reference,
            candidate,
            reference_url="https://retrostore.org",
            candidate_url="https://candidate.test",
            generated_at=datetime(2026, 8, 10, tzinfo=UTC),
        )

    assert report["scope"] == {"scenario_count": len(FALLBACK_SCENARIOS)}
    assert report["summary"] == {
        "total": 12,
        "matching": 12,
        "different": 0,
        "passes": True,
    }
    login = next(result for result in report["results"] if result["name"] == "missing-css")
    assert login["reference"] == {
        "status": 200,
        "content_type": "text/html",
        "behavior": "legacy_login_forward",
    }
    assert "conflogin" not in str(report)


def test_front_door_fallback_comparison_reports_only_changed_path() -> None:
    changed = "/vendor/__retrostore_front_door_fallback__.js"
    with _client() as reference, _client(changed_path=changed) as candidate:
        report = compare_front_door_fallback_clients(
            reference,
            candidate,
            reference_url="https://retrostore.org",
            candidate_url="https://candidate.test",
        )

    assert report["summary"]["different"] == 1
    assert report["differences"] == [{"name": "missing-vendor", "path": changed}]


def test_fallback_scenarios_are_excluded_from_every_migrating_route_group() -> None:
    routes_path = Path(__file__).parents[3] / "infra/front-door/route-groups.json"
    routes = json.loads(routes_path.read_text())
    migrating_paths = [
        route
        for group in routes["route_groups"]
        if group["future_backend"] != "app_engine_default"
        for route in group["paths"]
    ]

    for _, fallback in FALLBACK_SCENARIOS:
        assert not any(
            fallback == route["value"]
            if route["kind"] == "exact"
            else fallback.startswith(route["value"])
            for route in migrating_paths
        ), fallback

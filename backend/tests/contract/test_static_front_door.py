import hashlib
from datetime import UTC, datetime

import httpx

from retrostore.contract.static_front_door import (
    StaticExpectation,
    compare_static_client,
)


def _client(*, changed: bool = False) -> httpx.Client:
    def handle(request: httpx.Request) -> httpx.Response:
        body = b"changed" if changed and request.url.path == "/asset.js" else b"asset"
        return httpx.Response(
            200,
            headers={
                "Content-Type": "application/javascript; charset=utf-8",
                "Cache-Control": "no-store",
                "Access-Control-Allow-Origin": "*",
            },
            content=body,
        )

    return httpx.Client(
        transport=httpx.MockTransport(handle),
        base_url="http://candidate.test",
    )


def _expectation() -> StaticExpectation:
    return StaticExpectation(
        path="/asset.js",
        body_bytes=5,
        body_sha256=hashlib.sha256(b"asset").hexdigest(),
        content_type="application/javascript",
    )


def test_static_front_door_matches_body_headers_and_policy() -> None:
    with _client() as candidate:
        report = compare_static_client(
            candidate,
            [_expectation()],
            candidate_label="http://candidate.test",
            generated_at=datetime(2026, 8, 10, tzinfo=UTC),
        )

    assert report["summary"] == {
        "total": 1,
        "matching": 1,
        "different": 0,
        "passes": True,
    }
    assert report["scope"]["candidate_response_bytes"] == 5
    assert "asset" not in str(report)


def test_static_front_door_reports_changed_fields_without_body() -> None:
    with _client(changed=True) as candidate:
        report = compare_static_client(
            candidate,
            [_expectation()],
            candidate_label="http://candidate.test",
        )

    assert report["summary"]["passes"] is False
    assert report["differences"] == [
        {
            "path": "/asset.js",
            "fields": ["body_bytes", "body_sha256"],
        }
    ]
    assert "changed" not in str(report)

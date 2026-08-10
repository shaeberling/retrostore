from datetime import UTC, datetime

import httpx

from retrostore.contract.public_app_list import compare_public_app_clients


def _client(path: str, payload: list[dict[str, object]]) -> httpx.Client:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == path:
            return httpx.Response(200, json=payload)
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handle), base_url="https://test")


def _payload() -> list[dict[str, object]]:
    return [
        {
            "name": "App",
            "version": "1",
            "author": "Author",
            "description": "Description",
            "screenshots": ["https://images.example/one"],
            "reportUrl": "/reportapp?appId=secret-id",
            "downloadUrl": "/downloadapp?appId=secret-id",
            "emulatorAppId": "secret-id",
        }
    ]


def test_public_app_list_comparison_matches_semantically() -> None:
    with (
        _client("/rpc", _payload()) as reference,
        _client("/public/apps.json", _payload()) as candidate,
    ):
        report = compare_public_app_clients(
            reference,
            candidate,
            reference_url="https://retrostore.org",
            candidate_label="local",
            generated_at=datetime(2026, 8, 10, tzinfo=UTC),
        )

    assert report["summary"] == {"different": 0, "passes": True}
    assert report["scope"]["reference_app_count"] == 1
    assert "secret-id" not in str(report)
    assert "Description" not in str(report)


def test_public_app_list_comparison_reports_only_sanitized_fields() -> None:
    candidate_payload = _payload()
    candidate_payload[0] = {**candidate_payload[0], "description": "Changed"}
    with (
        _client("/rpc", _payload()) as reference,
        _client("/public/apps.json", candidate_payload) as candidate,
    ):
        report = compare_public_app_clients(
            reference,
            candidate,
            reference_url="https://retrostore.org",
            candidate_label="local",
        )

    assert report["summary"] == {"different": 1, "passes": False}
    assert report["differences"][0]["fields"] == ["description"]
    assert "secret-id" not in str(report)
    assert "Changed" not in str(report)

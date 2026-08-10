from datetime import UTC, datetime

import httpx

from retrostore.contract.public_redirects import compare_public_redirect_clients
from services.api_compat.app import LEGACY_PUBLIC_REDIRECTS, create_app


def _reference_client(*, wrong_destination: bool = False) -> httpx.Client:
    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path.rstrip("/")
        destination = LEGACY_PUBLIC_REDIRECTS.get(path)
        if destination is None:
            return httpx.Response(404)
        if wrong_destination and path == "/rsc":
            destination = "https://example.test/wrong"
        return httpx.Response(
            302,
            headers={"Location": destination, "Content-Type": "text/html"},
            content=b"",
        )

    return httpx.Client(
        transport=httpx.MockTransport(handle),
        base_url="https://retrostore.org",
        follow_redirects=False,
    )


def _candidate_client() -> httpx.Client:
    return httpx.Client(
        transport=httpx.WSGITransport(
            app=create_app({"TESTING": True, "RETROSTORE_REQUEST_LOGGING": False})
        ),
        base_url="http://candidate.test",
        follow_redirects=False,
    )


def test_public_redirect_comparison_matches_all_exact_paths() -> None:
    with _reference_client() as reference, _candidate_client() as candidate:
        report = compare_public_redirect_clients(
            reference,
            candidate,
            reference_url="https://retrostore.org",
            candidate_label="local",
            generated_at=datetime(2026, 8, 10, tzinfo=UTC),
        )

    assert report["scope"] == {"scenario_count": 6}
    assert report["summary"] == {
        "total": 6,
        "matching": 6,
        "different": 0,
        "passes": True,
    }
    assert report["differences"] == []


def test_public_redirect_comparison_reports_only_the_changed_path() -> None:
    with _reference_client(wrong_destination=True) as reference, _candidate_client() as candidate:
        report = compare_public_redirect_clients(
            reference,
            candidate,
            reference_url="https://retrostore.org",
            candidate_label="local",
        )

    assert report["summary"]["different"] == 2
    assert report["differences"] == [{"path": "/rsc"}, {"path": "/rsc/"}]
    assert "https://example.test/wrong" not in str(report["differences"])

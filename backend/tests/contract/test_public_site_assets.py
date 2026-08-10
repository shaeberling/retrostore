from datetime import UTC, datetime
from pathlib import Path

import httpx

from retrostore.contract.public_site_assets import (
    _legacy_source_bytes,
    compare_public_site_bundle,
)
from retrostore.public_site import build_public_site, legacy_static_content_type


def _reference() -> httpx.Client:
    def handle(request: httpx.Request) -> httpx.Response:
        object_path = "index.html" if request.url.path == "/" else request.url.path[1:]
        try:
            body = _legacy_source_bytes(object_path)
        except ValueError:
            return httpx.Response(404)
        return httpx.Response(
            200,
            content=body,
            headers={
                "Content-Type": legacy_static_content_type(object_path),
                "Access-Control-Allow-Origin": "*",
            },
        )

    return httpx.Client(
        transport=httpx.MockTransport(handle),
        base_url="https://retrostore.org",
        follow_redirects=False,
    )


def test_public_site_bundle_matches_legacy_source_with_six_transformations(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "site"
    build_public_site(candidate, generated_at=datetime(2026, 8, 10, tzinfo=UTC))

    with _reference() as reference:
        report = compare_public_site_bundle(
            reference,
            candidate,
            reference_url="https://retrostore.org",
            generated_at=datetime(2026, 8, 10, tzinfo=UTC),
        )

    assert report["scope"] == {
        "object_count": 78,
        "scenario_count": 79,
        "intentional_transformation_count": 6,
    }
    assert report["summary"] == {
        "total": 79,
        "matching": 79,
        "different": 0,
        "passes": True,
    }


def test_public_site_bundle_reports_a_tampered_file_without_body(tmp_path: Path) -> None:
    candidate = tmp_path / "site"
    build_public_site(candidate)
    (candidate / "css/modern-business.css").write_bytes(b"tampered")

    with _reference() as reference:
        report = compare_public_site_bundle(
            reference,
            candidate,
            reference_url="https://retrostore.org",
        )

    assert report["summary"]["different"] == 1
    assert report["differences"] == [
        {"path": "/css/modern-business.css", "failed_checks": ["candidate_matches_expected"]}
    ]
    assert "tampered" not in str(report)

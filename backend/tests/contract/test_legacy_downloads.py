from datetime import UTC, datetime
from pathlib import Path

import httpx

from retrostore.contract.legacy_downloads import (
    _candidate_origin,
    compare_download_clients,
    discover_download_scenarios,
)
from retrostore.mirror import load_catalog_mirror_archive
from services.api_compat.app import create_archive_app
from tests.mirror.test_archive import _write_archive


def test_discovers_and_matches_semantic_download_contract(tmp_path: Path) -> None:
    archive = tmp_path / "catalog.zip"
    _write_archive(archive)
    mirror = load_catalog_mirror_archive(archive)
    scenarios = discover_download_scenarios(mirror)
    app = create_archive_app(archive, {"TESTING": True})
    transport = httpx.WSGITransport(app=app)

    with httpx.Client(
        transport=transport, base_url="http://reference.test"
    ) as reference, httpx.Client(
        transport=transport, base_url="http://candidate.test"
    ) as candidate:
        report = compare_download_clients(
            reference,
            candidate,
            scenarios,
            reference_url="https://retrostore.org",
            candidate_label="test-candidate",
            generated_at=datetime(2026, 8, 10, tzinfo=UTC),
        )

    assert report["summary"] == {
        "total": 6,
        "matching": 6,
        "different": 0,
        "passes": True,
    }
    assert report["scope"]["zip_scenario_count"] == 1
    assert report["safety"]["contains_filenames"] is False


def test_detects_typed_media_difference_without_serializing_bytes(tmp_path: Path) -> None:
    archive = tmp_path / "catalog.zip"
    _write_archive(archive)
    mirror = load_catalog_mirror_archive(archive)
    reference_app = create_archive_app(archive, {"TESTING": True})
    candidate_app = create_archive_app(archive, {"TESTING": True})
    downloads = dict(candidate_app.config["RETROSTORE_LEGACY_DOWNLOADS"])
    value = downloads["app-1"]
    media = list(value.media)
    media[0] = type(media[0])(media[0].id, media[0].filename, b"changed")
    downloads["app-1"] = type(value)(value.name, tuple(media))
    candidate_app.config["RETROSTORE_LEGACY_DOWNLOADS"] = downloads

    with httpx.Client(
        transport=httpx.WSGITransport(app=reference_app),
        base_url="http://reference.test",
    ) as reference, httpx.Client(
        transport=httpx.WSGITransport(app=candidate_app),
        base_url="http://candidate.test",
    ) as candidate:
        report = compare_download_clients(
            reference,
            candidate,
            discover_download_scenarios(mirror),
            reference_url="https://retrostore.org",
            candidate_label="test-candidate",
        )

    assert report["summary"]["passes"] is False
    assert report["summary"]["different"] == 2
    assert all(
        "body_sha256" in item["fields"] or "zip_entries" in item["fields"]
        for item in report["differences"]
    )
    serialized = str(report)
    assert "changed" not in serialized
    assert "game.dmk" not in serialized


def test_candidate_url_guard_accepts_only_service_and_tagged_origins() -> None:
    service = (
        "https://retrostore-api-compat-candidate-760396810462.us-central1.run.app"
    )
    legacy_service = "https://retrostore-api-compat-candidate-zzch7qgr2a-uc.a.run.app"
    tagged = (
        "https://downloads1---retrostore-api-compat-candidate-zzch7qgr2a-uc.a.run.app/"
    )

    assert _candidate_origin(service) == service
    assert _candidate_origin(legacy_service) == legacy_service
    assert _candidate_origin(tagged) == tagged.rstrip("/")
    for invalid in (
        "http://retrostore-api-compat-candidate-760396810462.us-central1.run.app",
        "https://evil.example.test",
        f"{service}/api",
    ):
        try:
            _candidate_origin(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Expected candidate guard to reject {invalid}")

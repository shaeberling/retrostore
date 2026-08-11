from datetime import UTC, datetime

from retrostore.contract.public_transport_parity import (
    assemble_public_transport_report,
)


def _api() -> dict[str, object]:
    return {
        "scope": {
            "scenario_count": 158,
            "app_count": 32,
            "media_object_count": 60,
            "media_bytes": 6_826_237,
            "media_region_count": 60,
        },
        "summary": {"total": 158, "matching": 158, "different": 0},
        "approval_gate": {"passes": True, "difference_fields": 0},
        "results": [{"scenario": f"scenario-{index}", "differences": {}} for index in range(158)],
    }


def _surface(total: int) -> dict[str, object]:
    return {
        "summary": {
            "total": total,
            "matching": total,
            "different": 0,
            "passes": True,
        },
        "differences": [],
    }


def test_public_transport_report_combines_all_surfaces_without_values() -> None:
    report = assemble_public_transport_report(
        api=_api(),
        downloads=_surface(94),
        redirects=_surface(6),
        static_https=_surface(79),
        static_http=_surface(79),
        public_listing_matches=True,
        public_listing={
            "https": {"status": 200, "body_sha256": "a" * 64},
            "http": {"status": 200, "body_sha256": "a" * 64},
        },
        generated_at=datetime(2026, 8, 10, tzinfo=UTC),
    )

    assert report["scope"]["scenario_count"] == 338
    assert report["summary"] == {
        "total": 338,
        "matching": 338,
        "different": 0,
        "passes": True,
    }
    assert report["safety"]["contains_request_or_response_payloads"] is False


def test_public_transport_report_sanitizes_api_and_static_differences() -> None:
    api = _api()
    api["summary"] = {"total": 158, "matching": 157, "different": 1}
    api["approval_gate"] = {"passes": False, "difference_fields": 1}
    api["results"][0]["differences"] = {
        "semantic_body": {"expected": "catalog value", "actual": "changed"}
    }
    static_http = _surface(79)
    static_http["summary"] = {
        "total": 79,
        "matching": 78,
        "different": 1,
        "passes": False,
    }
    static_http["differences"] = [
        {"path": "/index.html", "failed_checks": ["reference_matches_source"]}
    ]

    report = assemble_public_transport_report(
        api=api,
        downloads=_surface(94),
        redirects=_surface(6),
        static_https=_surface(79),
        static_http=static_http,
        public_listing_matches=True,
        public_listing={"https": {}, "http": {}},
    )

    assert report["summary"]["different"] == 2
    assert report["summary"]["passes"] is False
    assert report["surfaces"]["api"]["differences"] == [
        {"scenario": "scenario-0", "fields": ["semantic_body"]}
    ]
    assert report["surfaces"]["public_static_site"]["differences"] == ["/index.html"]
    assert "catalog value" not in str(report)

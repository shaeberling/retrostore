from datetime import UTC, datetime
from pathlib import Path

import pytest

from retrostore.public_site import build_public_site
from retrostore.public_site_deployment import plan_public_site_deployment


def _bundle(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    bundle = tmp_path / "site"
    report = build_public_site(
        bundle,
        generated_at=datetime(2026, 8, 10, tzinfo=UTC),
    )
    return bundle, report


def test_static_deployment_plan_is_closed_create_only_and_not_executable(
    tmp_path: Path,
) -> None:
    bundle, report = _bundle(tmp_path)

    plan = plan_public_site_deployment(
        bundle,
        report,
        target_bucket="trs-80-retrostore-public",
        generated_at=datetime(2026, 8, 10, tzinfo=UTC),
    )

    assert plan["applied"] is False
    assert plan["production_changed"] is False
    assert plan["result"] == {
        "object_count": 78,
        "total_bytes": 4_652_747,
        "delete_count": 0,
        "ready_to_apply": False,
    }
    assert plan["operations"]["deletes"] == []
    assert len(plan["operations"]["uploads"]) == 78
    assert all(
        item["if_generation_match"] == 0
        and item["cache_control"] == "no-store"
        and "body" not in item
        for item in plan["operations"]["uploads"]
    )
    assert plan["target"]["website"] == {
        "main_page_suffix": "index.html",
        "not_found_page": None,
    }
    assert plan["target"]["required_location"] == "us-central1"
    routes = plan["front_door"]["static_matches"]
    assert routes["kind"] == "exact_only"
    assert routes["prefixes"] == []
    assert len(routes["paths"]) == 79
    assert "/" in routes["paths"]
    assert "/public/apps.html" in routes["paths"]
    assert "/public/apps.json" not in routes["paths"]
    assert plan["front_door"]["unknown_path_disposition"] == "app_engine_default"
    assert plan["safety"]["apply_capability_present"] is False
    assert plan["proposed_initial_policy"]["status"] == ("approved_simple_hobby_project_policy")
    assert plan["proposed_initial_policy"]["root_request_resolution"] == (
        "cloud_storage_main_page_suffix"
    )
    assert plan["proposed_initial_policy"]["deployment_strategy"] == ("single_dedicated_bucket")
    assert plan["proposed_initial_policy"]["cdn_enabled"] is False
    assert plan["proposed_initial_policy"]["cache_control"] == "no-store"
    assert "Cloud CDN later" in plan["proposed_initial_policy"]["future_optional_optimization"]
    assert plan["required_external_approvals"] == []


@pytest.mark.parametrize(
    "bucket",
    [
        "trs-80-retrostore-assets",
        "trs-80-retrostore-state",
        "trs-80.appspot.com",
        "staging.trs-80.appspot.com",
        "us.artifacts.trs-80.appspot.com",
    ],
)
def test_static_deployment_plan_refuses_every_known_existing_bucket(
    tmp_path: Path, bucket: str
) -> None:
    bundle, report = _bundle(tmp_path)

    with pytest.raises(ValueError, match="existing protected bucket"):
        plan_public_site_deployment(bundle, report, target_bucket=bucket)


def test_static_deployment_plan_rejects_non_public_bucket_namespace(
    tmp_path: Path,
) -> None:
    bundle, report = _bundle(tmp_path)

    with pytest.raises(ValueError, match="must be exactly"):
        plan_public_site_deployment(
            bundle,
            report,
            target_bucket="some-other-bucket",
        )


def test_static_deployment_plan_rejects_tampered_file(tmp_path: Path) -> None:
    bundle, report = _bundle(tmp_path)
    (bundle / "index.html").write_text("tampered")

    with pytest.raises(ValueError, match="differs from build report"):
        plan_public_site_deployment(
            bundle,
            report,
            target_bucket="trs-80-retrostore-public",
        )


def test_static_deployment_plan_rejects_extra_file(tmp_path: Path) -> None:
    bundle, report = _bundle(tmp_path)
    (bundle / "extra.txt").write_text("unexpected")

    with pytest.raises(ValueError, match="object sets differ"):
        plan_public_site_deployment(
            bundle,
            report,
            target_bucket="trs-80-retrostore-public",
        )

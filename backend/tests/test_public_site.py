import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from retrostore.public_site import build_public_site


def test_static_public_site_build_is_closed_and_rewrites_catalog_fetch(
    tmp_path: Path,
) -> None:
    output = tmp_path / "site"

    report = build_public_site(output, generated_at=datetime(2026, 8, 10, tzinfo=UTC))

    assert report["production_changed"] is False
    assert report["result"]["file_count"] > 20
    assert report["result"]["missing_static_reference_count"] == 0
    assert report["result"]["unrouted_static_file_count"] == 0
    apps = (output / "apps.html").read_text()
    assert "/public/apps.json" in apps
    assert "/rpc?m=pubapplist" not in apps
    assert "/public/lightbox2/" not in apps
    assert (output / "favicon/favicon-32x32.png").is_file()
    assert (output / "gfx/discord.svg").is_file()
    assert not (output / "contact.html").read_text().count("contact_me.js")
    assert (output / "public/apps.html").read_text() == apps
    assert not (output / "public/apps.json").exists()
    assert report["routes"]["dynamic_exact_exclusion"] == "/public/apps.json"
    assert report["routes"]["prefix"] == []
    assert len(report["routes"]["exact"]) == 79
    assert "/public/apps.html" in report["routes"]["exact"]
    assert report["transformations"] == {
        "lightbox_paths_rewritten": 4,
        "missing_contact_scripts_removed": 4,
        "public_app_list_fetch_rewritten": 2,
    }
    objects = {value["path"]: value for value in report["objects"]}
    assert objects["index.html"]["content_type"] == "text/html"
    assert objects["vendor/jquery/jquery.min.js"]["content_type"] == ("application/javascript")
    assert objects["favicon.ico"]["content_type"] == "text/plain"
    assert objects["lightbox2/images/loading.gif"]["content_type"] == "text/plain"
    assert objects["favicon/favicons.zip"]["content_type"] == "text/plain"


def test_static_public_site_build_is_create_only(tmp_path: Path) -> None:
    output = tmp_path / "site"
    output.mkdir()

    with pytest.raises(FileExistsError):
        build_public_site(output)


def test_static_builder_and_front_door_route_manifest_stay_in_sync(
    tmp_path: Path,
) -> None:
    routes_path = Path(__file__).parents[2] / "infra/front-door/route-groups.json"
    plan = json.loads(routes_path.read_text())
    static = next(group for group in plan["route_groups"] if group["id"] == "public_static_site")
    report = build_public_site(tmp_path / "site")

    assert {(entry["kind"], entry["value"]) for entry in static["paths"]} == {
        *(("exact", path) for path in report["routes"]["exact"]),
    }
    assert static["handoff_group"] == "public_website"

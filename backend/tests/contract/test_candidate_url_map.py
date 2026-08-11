import json
from pathlib import Path

import pytest

from retrostore.contract.candidate_url_map import render_candidate_url_map

ROUTES_PATH = Path(__file__).parents[3] / "infra/front-door/route-groups.json"


def _routes() -> dict[str, object]:
    return json.loads(ROUTES_PATH.read_text())


def test_candidate_url_map_is_complete_and_fails_unknown_paths_to_app_engine() -> None:
    rendered = render_candidate_url_map(_routes())

    assert rendered["name"] == "retrostore-next"
    assert {rule["hosts"][0] for rule in rendered["hostRules"]} == {
        "next.retrostore.org",
        "admin-next.retrostore.org",
    }
    matchers = {matcher["name"]: matcher for matcher in rendered["pathMatchers"]}
    candidate = matchers["parallel-candidate"]
    rules = {
        rule["service"].rsplit("/", 1)[-1]: set(rule["paths"]) for rule in candidate["pathRules"]
    }
    api_paths = rules["retrostore-api-next"]
    static_paths = rules["retrostore-public-static"]
    assert len(api_paths) == 19
    assert "/api/listApps" in api_paths
    assert "/api/uploadState" in api_paths
    assert "/api/*" not in api_paths
    assert len(static_paths) == 79
    assert "/" in static_paths
    assert "/public/apps.json" not in static_paths
    assert candidate["defaultService"].endswith("/retrostore-appengine-default")
    assert matchers["admin-candidate"]["defaultService"].endswith("/retrostore-admin-next")


def test_candidate_url_map_rejects_an_unknown_api_wildcard() -> None:
    routes = _routes()
    group = next(group for group in routes["route_groups"] if group["id"] == "catalog_api_reads")
    group["paths"].append({"kind": "prefix", "value": "/api/"})

    with pytest.raises(ValueError, match="cannot claim unknown API methods"):
        render_candidate_url_map(routes)

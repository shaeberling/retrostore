import copy
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

REPOSITORY_ROOT = Path(__file__).parents[2]
ROUTES_PATH = REPOSITORY_ROOT / "infra/front-door/route-groups.json"
VALIDATOR_PATH = REPOSITORY_ROOT / "infra/front-door/validate.py"


def _validator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("front_door_validate", VALIDATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _routes() -> dict[str, object]:
    return json.loads(ROUTES_PATH.read_text())


def _group(routes: dict[str, object], group_id: str) -> dict[str, object]:
    groups = routes["route_groups"]
    assert isinstance(groups, list)
    return next(group for group in groups if group["id"] == group_id)


def test_checked_in_front_door_routes_are_collision_closed() -> None:
    _validator().validate_routes(_routes())


def test_undeclared_exact_prefix_overlap_is_rejected() -> None:
    routes = copy.deepcopy(_routes())
    group = _group(routes, "public_redirects")
    group["paths"].append({"kind": "exact", "value": "/public/other.json"})

    with pytest.raises(ValueError, match="declarations do not match overlaps"):
        _validator().validate_routes(routes)


def test_duplicate_exact_route_is_rejected() -> None:
    routes = copy.deepcopy(_routes())
    group = _group(routes, "public_redirects")
    group["paths"].append({"kind": "exact", "value": "/apps.html"})

    with pytest.raises(ValueError, match="duplicate exact route /apps.html"):
        _validator().validate_routes(routes)


def test_overlapping_prefix_routes_are_rejected() -> None:
    routes = copy.deepcopy(_routes())
    group = _group(routes, "public_report")
    group["paths"].append({"kind": "prefix", "value": "/public/reports/"})

    with pytest.raises(ValueError, match="overlapping route prefixes"):
        _validator().validate_routes(routes)


def test_plain_http_cannot_be_removed_or_redirected_during_migration() -> None:
    routes = copy.deepcopy(_routes())
    routes["front_door"]["preserve_plain_http"] = False
    routes["front_door"]["plain_http_compatibility"]["redirect_to_https"] = True

    with pytest.raises(ValueError, match="plain HTTP must be preserved"):
        _validator().validate_routes(routes)

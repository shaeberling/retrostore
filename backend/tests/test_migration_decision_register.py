import copy
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

REPOSITORY_ROOT = Path(__file__).parents[2]
REGISTER_PATH = REPOSITORY_ROOT / "infra/readiness/decision-register.json"
ROUTES_PATH = REPOSITORY_ROOT / "infra/front-door/route-groups.json"
THRESHOLDS_PATH = REPOSITORY_ROOT / "infra/front-door/monitoring-thresholds.json"
RETENTION_PATH = REPOSITORY_ROOT / "infra/data-retention/retention-policy.json"
VALIDATOR_PATH = REPOSITORY_ROOT / "infra/readiness/validate.py"


def _validator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("readiness_validate", VALIDATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text())


def _values() -> tuple[dict[str, object], ...]:
    return tuple(
        _load(path)
        for path in (REGISTER_PATH, ROUTES_PATH, THRESHOLDS_PATH, RETENTION_PATH)
    )


def test_checked_in_decision_register_matches_all_pending_policy_sources() -> None:
    _validator().validate(*_values())


def test_decision_register_cannot_silently_omit_a_pending_choice() -> None:
    register, routes, thresholds, retention = copy.deepcopy(_values())
    register["pending"] = [
        item for item in register["pending"] if item["id"] != "alert_destination"
    ]

    with pytest.raises(ValueError, match="register is incomplete"):
        _validator().validate(register, routes, thresholds, retention)


def test_decision_register_cannot_silently_authorize_traffic() -> None:
    register, routes, thresholds, retention = copy.deepcopy(_values())
    register["readiness"]["production_traffic_change_ready"] = True

    with pytest.raises(ValueError, match="cannot authorize public work"):
        _validator().validate(register, routes, thresholds, retention)


def test_decision_register_detects_out_of_band_owner_assignment() -> None:
    register, routes, thresholds, retention = copy.deepcopy(_values())
    routes["ownership"]["go_no_go"]["confirmed_owner"] = "unconfirmed"

    with pytest.raises(ValueError, match="differs from route plan"):
        _validator().validate(register, routes, thresholds, retention)

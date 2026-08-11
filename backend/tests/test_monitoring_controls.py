import copy
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

REPOSITORY_ROOT = Path(__file__).parents[2]
MONITORING_ROOT = REPOSITORY_ROOT / "infra/monitoring"
VALIDATOR_PATH = MONITORING_ROOT / "validate.py"


def _validator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("monitoring_validate", VALIDATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text())


def _values() -> tuple[dict[str, object], ...]:
    return tuple(
        _load(path)
        for path in (
            MONITORING_ROOT / "dashboard.json",
            MONITORING_ROOT / "comparator-failure-policy.json",
            MONITORING_ROOT / "comparator-stale-policy.json",
            REPOSITORY_ROOT / "infra/readiness/decision-register.json",
        )
    )


def test_checked_in_monitoring_controls_are_current_disabled_and_channel_free() -> None:
    _validator().validate(*_values())


def test_monitoring_controls_reject_silent_alert_enablement() -> None:
    dashboard, failure, stale, decisions = copy.deepcopy(_values())
    failure["enabled"] = True

    with pytest.raises(ValueError, match="must remain disabled"):
        _validator().validate(dashboard, failure, stale, decisions)


def test_monitoring_controls_reject_unapproved_notification_channel() -> None:
    dashboard, failure, stale, decisions = copy.deepcopy(_values())
    stale["notificationChannels"] = ["projects/trs-80/notificationChannels/1"]

    with pytest.raises(ValueError, match="cannot attach a channel"):
        _validator().validate(dashboard, failure, stale, decisions)


def test_monitoring_controls_require_current_four_surface_dashboard_text() -> None:
    dashboard, failure, stale, decisions = copy.deepcopy(_values())
    dashboard["mosaicLayout"]["tiles"][0]["widget"]["text"]["content"] = "Old 158-only dashboard"

    with pytest.raises(ValueError, match="missing API 158"):
        _validator().validate(dashboard, failure, stale, decisions)

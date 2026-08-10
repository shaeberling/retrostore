#!/usr/bin/env python3
"""Validate disabled migration monitoring controls without cloud access."""

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DASHBOARD_PATH = ROOT / "dashboard.json"
FAILURE_POLICY_PATH = ROOT / "comparator-failure-policy.json"
STALE_POLICY_PATH = ROOT / "comparator-stale-policy.json"
DECISIONS_PATH = ROOT.parent / "readiness/decision-register.json"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate(
    dashboard: dict[str, Any],
    failure: dict[str, Any],
    stale: dict[str, Any],
    decisions: dict[str, Any],
) -> None:
    _require(
        dashboard.get("name")
        == "projects/760396810462/dashboards/retrostore-migration",
        "dashboard identity changed",
    )
    text_tiles = [
        tile["widget"]["text"]["content"]
        for tile in dashboard["mosaicLayout"]["tiles"]
        if "text" in tile["widget"]
    ]
    _require(len(text_tiles) == 1, "dashboard must contain one gate summary")
    gate_text = text_tiles[0]
    for marker in (
        "API 158",
        "downloads 94",
        "website catalog 32",
        "redirects 6",
        "338 public reads",
        "Card and TRS-IO remain on App Engine",
    ):
        _require(marker in gate_text, f"dashboard gate summary is missing {marker}")

    for policy in (failure, stale):
        _require(policy.get("enabled") is False, "alert policy must remain disabled")
        _require(
            "notificationChannels" not in policy,
            "alert policy cannot attach a channel before approval",
        )
        _require(
            "disabled pending channel" in policy.get("displayName", ""),
            "alert policy must show its pending-channel state",
        )
    failure_filter = failure["conditions"][0]["conditionMatchedLog"]["filter"]
    _require(
        'jsonPayload.approval_gate.passes=false' in failure_filter,
        "difference policy does not require a failed aggregate gate",
    )
    absent = stale["conditions"][0]["conditionAbsent"]
    _require(absent["duration"] == "5400s", "stale evidence threshold changed")
    _require(
        "retrostore_comparison_pass" in absent["filter"],
        "stale policy does not use the passing-comparison metric",
    )

    pending = {item["id"]: item for item in decisions["pending"]}
    _require(
        pending["alert_destination"]["status"] == "confirmation_required"
        and pending["alert_destination"]["proposal"] is None,
        "monitoring source differs from the pending alert decision",
    )


def main() -> int:
    validate(
        _load(DASHBOARD_PATH),
        _load(FAILURE_POLICY_PATH),
        _load(STALE_POLICY_PATH),
        _load(DECISIONS_PATH),
    )
    print("monitoring dashboard and disabled-alert invariants: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

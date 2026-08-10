#!/usr/bin/env python3
"""Validate front-door routing and safety invariants without cloud writes."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
ROUTES_PATH = ROOT / "route-groups.json"
THRESHOLDS_PATH = ROOT / "monitoring-thresholds.json"
PRIVATE_SOAK_PATH = ROOT / "private-soak-baseline.json"

FROZEN_API_METHODS = {
    "getApp",
    "listApps",
    "listAppsNano",
    "fetchMediaImages",
    "fetchMediaImageRefs",
    "fetchMediaImageRegion",
    "uploadState",
    "downloadState",
    "downloadStateMemoryRegion",
}
STATE_METHODS = {
    "uploadState",
    "downloadState",
    "downloadStateMemoryRegion",
}
HARDWARE_PATHS = {
    ("exact", "/card"),
    ("prefix", "/card/"),
    ("exact", "/trs-io"),
    ("prefix", "/trs-io/"),
}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _paths(group: dict[str, Any]) -> set[tuple[str, str]]:
    return {(path["kind"], path["value"]) for path in group["paths"]}


def _api_methods(groups: list[dict[str, Any]]) -> dict[str, str]:
    owners: dict[str, str] = {}
    for group in groups:
        for kind, path in _paths(group):
            if kind != "exact" or not path.startswith("/api/"):
                continue
            method = path.removeprefix("/api/")
            _require(method not in owners, f"API method {method} appears in two route groups")
            owners[method] = group["id"]
    return owners


def validate_routes(routes: dict[str, Any]) -> None:
    _require(routes.get("schema_version") == 1, "unsupported route schema")
    _require(routes.get("project") == "trs-80", "route project must be trs-80")
    _require(
        routes["front_door"]["production_baseline_backend"] == "app_engine_default",
        "the production front-door baseline must route to App Engine",
    )
    _require(
        routes["front_door"]["transparent_request_mirroring"] is False,
        "serverless backends must not claim transparent request mirroring",
    )

    hostnames = routes["hostnames"]
    hostname_values = [entry["value"] for entry in hostnames.values()]
    _require(len(hostname_values) == len(set(hostname_values)), "hostnames must be distinct")
    for name in ("front_door_rehearsal", "candidate_api", "candidate_admin"):
        _require(
            hostnames[name]["status"] == "confirmation_required",
            f"{name} must remain confirmation-required until approved",
        )

    for role in ("go_no_go", "rollback_operator"):
        owner = routes["ownership"][role]
        _require(owner["confirmed_owner"] is None, f"{role} was assigned without confirmation")
        _require(owner["status"] == "confirmation_required", f"{role} must require confirmation")

    groups = routes["route_groups"]
    by_id = {group["id"]: group for group in groups}
    _require(len(by_id) == len(groups), "route group IDs must be unique")

    hardware = by_id["hardware_update"]
    _require(_paths(hardware) == HARDWARE_PATHS, "hardware route island is incomplete")
    _require(
        hardware["current_backend"] == hardware["future_backend"] == "app_engine_default",
        "hardware routes must stay on App Engine",
    )
    _require(hardware["migration_mode"] == "never_cut_over", "hardware routes cannot migrate")
    _require(not hardware["canary_steps_percent"], "hardware routes cannot be canaried")

    api_owners = _api_methods(groups)
    _require(set(api_owners) == FROZEN_API_METHODS, "all frozen API methods must be routed exactly")
    state = by_id["state_api"]
    state_methods = {path.removeprefix("/api/") for _, path in _paths(state)}
    _require(state_methods == STATE_METHODS, "all state methods must form one route group")
    _require(
        state["migration_mode"] == "atomic_single_writer_handoff",
        "state methods require an atomic handoff",
    )
    _require(not state["canary_steps_percent"], "state methods cannot be canaried")

    for group_id in ("catalog_api_reads", "media_api_reads"):
        group = by_id[group_id]
        _require(group["migration_mode"] == "weighted_read_canary", f"{group_id} must canary")
        _require(
            group["canary_steps_percent"] == [1, 5, 25, 50, 100],
            f"{group_id} has unexpected canary steps",
        )

    admin = by_id["new_admin"]
    _require(
        admin["migration_mode"] == "atomic_single_writer_handoff",
        "admin writers require an atomic handoff",
    )
    _require(not admin["canary_steps_percent"], "admin writers cannot be canaried")

    production = routes["candidate_maps"]["production_initial"]
    _require(production["default_backend"] == "app_engine_default", "initial production changed")
    _require(not production["route_overrides"], "initial production must have no route overrides")


def validate_thresholds(thresholds: dict[str, Any]) -> None:
    _require(thresholds.get("schema_version") == 1, "unsupported threshold schema")
    comparison = thresholds["comparison"]
    _require(comparison["schedule_seconds"] <= 3600, "comparison must run at least hourly")
    _require(comparison["continuous_zero_diff_soak_days"] >= 14, "zero-diff soak is too short")
    _require(comparison["maximum_unexplained_differences"] == 0, "differences must be zero")
    _require(comparison["maximum_unapproved_differences"] == 0, "unapproved diffs must be zero")

    integrity = thresholds["integrity"]
    for name in (
        "maximum_missing_documents",
        "maximum_missing_objects",
        "maximum_checksum_mismatches",
        "maximum_broken_references",
        "maximum_duplicate_ids",
    ):
        _require(integrity[name] == 0, f"{name} must be zero")

    canary = thresholds["canary"]
    _require(canary["read_steps_percent"] == [1, 5, 25, 50, 100], "canary steps differ")
    _require(canary["state_canary_allowed"] is False, "state canary must be disabled")
    _require(canary["admin_writer_canary_allowed"] is False, "admin canary must be disabled")
    _require(
        thresholds["rollback"]["target_route_recovery_minutes"] <= 5,
        "route rollback target exceeds five minutes",
    )


def validate_private_soak(baseline: dict[str, Any]) -> None:
    _require(baseline.get("schema_version") == 1, "unsupported private soak schema")
    _require(
        baseline.get("status") == "private_evidence_only_no_cutover_authority",
        "private soak must not imply cutover authority",
    )
    _require(baseline.get("project") == "trs-80", "private soak project must be trs-80")
    _require(baseline.get("region") == "us-central1", "private soak region changed")
    _require(
        baseline.get("service") == "retrostore-api-compat-candidate",
        "private soak service changed",
    )
    _require(
        baseline.get("candidate_url")
        == "https://retrostore-api-compat-candidate-760396810462.us-central1.run.app",
        "private soak candidate URL changed",
    )
    revision = baseline.get("revision")
    _require(
        isinstance(revision, str)
        and revision.startswith("retrostore-api-compat-candidate-"),
        "private soak revision is invalid",
    )
    ready_at = baseline.get("revision_ready_at")
    not_before = baseline.get("soak_not_before")
    try:
        ready_timestamp = datetime.fromisoformat(ready_at.replace("Z", "+00:00"))
        boundary_timestamp = datetime.fromisoformat(not_before.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as error:
        raise ValueError("private soak timestamps are invalid") from error
    _require(
        boundary_timestamp >= ready_timestamp,
        "private soak boundary predates revision readiness",
    )
    for name in (
        "production_routing_changed",
        "catalog_activation_authorized",
        "load_balancer_authorized",
    ):
        _require(baseline.get(name) is False, f"private soak unexpectedly authorizes {name}")


def main() -> int:
    validate_routes(_load(ROUTES_PATH))
    validate_thresholds(_load(THRESHOLDS_PATH))
    validate_private_soak(_load(PRIVATE_SOAK_PATH))
    print("front-door route, threshold, and private-soak invariants: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

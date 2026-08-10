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
PUBLIC_REDIRECT_PATHS = {
    ("exact", "/community"),
    ("exact", "/community/"),
    ("exact", "/rsc"),
    ("exact", "/rsc/"),
    ("exact", "/app"),
    ("exact", "/app/"),
}
PUBLIC_STATIC_PATHS = {
    ("exact", "/"),
    ("exact", "/404.html"),
    ("exact", "/LICENSE"),
    ("exact", "/apps.html"),
    ("exact", "/contact.html"),
    ("exact", "/emulator.html"),
    ("exact", "/favicon.ico"),
    ("exact", "/full-width.html"),
    ("exact", "/index.html"),
    ("exact", "/signup.html"),
    ("prefix", "/css/"),
    ("prefix", "/favicon/"),
    ("prefix", "/gfx/"),
    ("prefix", "/js/"),
    ("prefix", "/lightbox2/"),
    ("prefix", "/public/"),
    ("prefix", "/vendor/"),
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


def _validate_route_overlaps(routes: dict[str, Any]) -> None:
    """Require every same-host exact/prefix overlap to be explicit and atomic."""
    overlaps: set[tuple[str, str, str, str, str]] = set()
    groups = routes["route_groups"]
    for index, left_group in enumerate(groups):
        left_host = left_group.get("host", routes["hostnames"]["production"]["value"])
        for right_group in groups[index + 1 :]:
            right_host = right_group.get(
                "host", routes["hostnames"]["production"]["value"]
            )
            if left_host != right_host:
                continue
            for left_kind, left_path in _paths(left_group):
                for right_kind, right_path in _paths(right_group):
                    if "default" in {left_kind, right_kind}:
                        continue
                    if left_kind == right_kind == "exact":
                        _require(
                            left_path != right_path,
                            f"duplicate exact route {left_path} on {left_host}",
                        )
                        continue
                    if left_kind == right_kind == "prefix":
                        _require(
                            not (
                                left_path.startswith(right_path)
                                or right_path.startswith(left_path)
                            ),
                            f"overlapping route prefixes {left_path} and {right_path} "
                            f"on {left_host}",
                        )
                        continue
                    if left_kind == "exact":
                        exact_group, exact_path = left_group, left_path
                        prefix_group, prefix_path = right_group, right_path
                    else:
                        exact_group, exact_path = right_group, right_path
                        prefix_group, prefix_path = left_group, left_path
                    if exact_path.startswith(prefix_path):
                        overlaps.add(
                            (
                                left_host,
                                exact_group["id"],
                                exact_path,
                                prefix_group["id"],
                                prefix_path,
                            )
                        )

    declared: set[tuple[str, str, str, str, str]] = set()
    groups_by_id = {group["id"]: group for group in groups}
    for rule in routes.get("path_precedence", []):
        high = rule["higher_priority_path"]
        low = rule["lower_priority_path"]
        _require(
            high["kind"] == "exact" and low["kind"] == "prefix",
            "path precedence must place one exact path above one prefix",
        )
        high_group = groups_by_id[rule["higher_priority_group"]]
        low_group = groups_by_id[rule["lower_priority_group"]]
        _require(
            (high["kind"], high["value"]) in _paths(high_group)
            and (low["kind"], low["value"]) in _paths(low_group),
            "path precedence references a route outside its declared group",
        )
        _require(
            high_group.get("handoff_group") == rule["handoff_group"]
            and low_group.get("handoff_group") == rule["handoff_group"],
            "overlapping routes must move in one atomic handoff group",
        )
        declared.add(
            (
                rule["host"],
                rule["higher_priority_group"],
                high["value"],
                rule["lower_priority_group"],
                low["value"],
            )
        )
    _require(
        overlaps == declared,
        f"route precedence declarations do not match overlaps: "
        f"observed={sorted(overlaps)!r}, declared={sorted(declared)!r}",
    )


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
    front_door = routes["front_door"]
    plain_http = front_door["plain_http_compatibility"]
    _require(front_door["preserve_plain_http"] is True, "plain HTTP must be preserved")
    _require(
        plain_http["status"] == "required_for_in_place_migration"
        and plain_http["port"] == 80
        and plain_http["redirect_to_https"] is False
        and plain_http["frontend_behavior"] == "route_through_same_url_map"
        and plain_http["deprecation_scope"] == "separate_future_client_migration",
        "plain HTTP compatibility policy changed",
    )
    _require(
        len(plain_http["reviewed_evidence"]) >= 2,
        "plain HTTP compatibility requires reviewed native-client evidence",
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
    _validate_route_overlaps(routes)

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

    for group_id in ("catalog_api_reads", "media_api_reads", "legacy_media_download"):
        group = by_id[group_id]
        _require(group["migration_mode"] == "weighted_read_canary", f"{group_id} must canary")
        _require(
            group["canary_steps_percent"] == [1, 5, 25, 50, 100],
            f"{group_id} has unexpected canary steps",
        )
    _require(
        _paths(by_id["legacy_media_download"]) == {("exact", "/downloadapp")},
        "only the exact tested legacy download path may move",
    )

    admin = by_id["new_admin"]
    _require(
        admin["migration_mode"] == "atomic_single_writer_handoff",
        "admin writers require an atomic handoff",
    )
    _require(not admin["canary_steps_percent"], "admin writers cannot be canaried")

    legacy_admin = by_id["legacy_catalog_admin"]
    _require(
        ("prefix", "/screenshotServe") in _paths(legacy_admin),
        "the login-protected legacy screenshot preview belongs to the legacy admin",
    )
    _require(
        "legacy_screenshot_assets" not in by_id,
        "the login-protected screenshot preview must not be classified as a public asset route",
    )
    public_website = by_id["public_website_catalog"]
    _require(
        _paths(public_website) == {("exact", "/public/apps.json")},
        "the candidate public website JSON route changed unexpectedly",
    )
    _require(
        public_website["migration_mode"] == "atomic_route_change"
        and not public_website["canary_steps_percent"],
        "the public website and its JSON dependency must move together",
    )
    public_static = by_id["public_static_site"]
    _require(
        _paths(public_static) == PUBLIC_STATIC_PATHS,
        "the public static website route closure changed unexpectedly",
    )
    _require(
        public_static["future_backend"] == "static_backend_bucket"
        and public_static["migration_mode"] == "atomic_route_change"
        and not public_static["canary_steps_percent"],
        "the public static website requires one atomic backend-bucket move",
    )
    public_redirects = by_id["public_redirects"]
    _require(
        _paths(public_redirects) == PUBLIC_REDIRECT_PATHS,
        "the six exact legacy public redirects changed unexpectedly",
    )
    _require(
        public_redirects["migration_mode"] == "atomic_route_change"
        and not public_redirects["canary_steps_percent"],
        "public redirects require one atomic route change",
    )
    for group in (public_static, public_website, public_redirects):
        _require(
            group.get("handoff_group") == "public_website",
            "static files, catalog JSON, and redirects must share one handoff group",
        )
    _require(
        ("prefix", "/public/") in _paths(public_static)
        and ("exact", "/public/apps.json") in _paths(public_website),
        "the exact dynamic catalog route must override the legacy /public/ alias",
    )

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
    _require(
        canary["require_plain_http_full_corpus_at_each_step"] is True,
        "every canary step requires the full plain-HTTP corpus",
    )
    _require(
        canary["require_native_port_80_smoke_at_each_step"] is True,
        "every canary step requires a native port-80 smoke",
    )
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
    _require(
        baseline.get("evidence_schema_version") == 3,
        "private soak must require four-surface evidence schema 3",
    )
    _require(
        baseline.get("required_surfaces")
        == ["frozen_api", "legacy_downloads", "public_app_list", "public_redirects"],
        "private soak required surfaces changed unexpectedly",
    )
    _require(
        baseline.get("comparator_job_generation") == 4,
        "private soak comparator generation changed unexpectedly",
    )
    digest = baseline.get("comparator_image_digest")
    _require(
        isinstance(digest, str) and digest.startswith("sha256:") and len(digest) == 71,
        "private soak comparator digest is invalid",
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

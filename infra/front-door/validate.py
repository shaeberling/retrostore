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
PUBLIC_CANDIDATE_PATH = ROOT / "public-candidate-baseline.json"

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
REPOSITORY_ROOT = ROOT.parents[1]


def _public_static_paths() -> set[tuple[str, str]]:
    web_inf = REPOSITORY_ROOT / "appengine/src/main/webapp/WEB-INF"
    public = web_inf / "public"
    favicon = web_inf / "favicon"
    gfx = web_inf / "gfx"
    _require(
        public.is_dir() and favicon.is_dir() and gfx.is_dir(),
        "legacy public source directories are missing",
    )
    public_files = [
        path.relative_to(public).as_posix()
        for path in public.rglob("*")
        if path.is_file()
    ]
    favicon_files = [
        path.relative_to(favicon).as_posix()
        for path in favicon.rglob("*")
        if path.is_file()
    ]
    gfx_files = [path.relative_to(gfx).as_posix() for path in gfx.rglob("*") if path.is_file()]
    values = {
        "/",
        "/favicon.ico",
        *(f"/{path}" for path in public_files),
        *(f"/public/{path}" for path in public_files),
        *(f"/favicon/{path}" for path in favicon_files),
        *(f"/gfx/{path}" for path in gfx_files),
    }
    return {("exact", value) for value in values}


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
    _require(
        routes.get("status") == "parallel_candidate_deployed_dns_pending",
        "candidate deployment status changed unexpectedly",
    )
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
    _require(
        hostnames["parallel_candidate"]["value"] == "next.retrostore.org"
        and hostnames["candidate_admin"]["value"] == "admin-next.retrostore.org",
        "approved candidate hostnames changed",
    )
    backends = routes["backends"]
    _require(
        backends["cloud_run_api"] == {
            "kind": "cloud_run",
            "service": "retrostore-api-next",
            "status": "public_candidate_ready",
        },
        "public API candidate backend changed",
    )
    _require(
        backends["cloud_run_admin"] == {
            "kind": "cloud_run",
            "service": "retrostore-admin-next",
            "status": "public_candidate_ready",
        },
        "public admin candidate backend changed",
    )
    _require(
        backends["static_backend_bucket"].get("bucket")
        == "trs-80-retrostore-public"
        and backends["static_backend_bucket"].get("cdn_enabled") is False
        and backends["static_backend_bucket"].get("status")
        == "public_candidate_ready",
        "public static candidate backend changed",
    )
    for name in ("parallel_candidate", "candidate_admin"):
        _require(
            hostnames[name]["status"] == "approved",
            f"{name} must retain its approved hostname",
        )

    for role in ("go_no_go", "rollback_operator"):
        owner = routes["ownership"][role]
        _require(owner["confirmed_owner"] == "Sascha Ha", f"{role} owner changed")
        _require(owner["status"] == "approved", f"{role} approval changed")

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
    _require(not hardware["traffic_split_steps_percent"], "hardware routes cannot split traffic")

    api_owners = _api_methods(groups)
    _require(set(api_owners) == FROZEN_API_METHODS, "all frozen API methods must be routed exactly")
    state = by_id["state_api"]
    state_methods = {path.removeprefix("/api/") for _, path in _paths(state)}
    _require(state_methods == STATE_METHODS, "all state methods must form one route group")
    _require(
        state["migration_mode"] == "atomic_single_writer_handoff",
        "state methods require an atomic handoff",
    )
    _require(not state["traffic_split_steps_percent"], "state methods cannot split traffic")

    for group_id in ("catalog_api_reads", "media_api_reads", "legacy_media_download"):
        group = by_id[group_id]
        _require(
            group["migration_mode"] == "atomic_route_change",
            f"{group_id} must use the single production cutover",
        )
        _require(
            not group["traffic_split_steps_percent"],
            f"{group_id} cannot use percentage traffic steps",
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
    _require(not admin["traffic_split_steps_percent"], "admin writers cannot split traffic")

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
        and not public_website["traffic_split_steps_percent"],
        "the public website and its JSON dependency must move together",
    )
    public_static = by_id["public_static_site"]
    _require(
        _paths(public_static) == _public_static_paths(),
        "the public static website route closure changed unexpectedly",
    )
    _require(
        public_static["future_backend"] == "static_backend_bucket"
        and public_static["migration_mode"] == "atomic_route_change"
        and not public_static["traffic_split_steps_percent"],
        "the public static website requires one atomic backend-bucket move",
    )
    public_redirects = by_id["public_redirects"]
    _require(
        _paths(public_redirects) == PUBLIC_REDIRECT_PATHS,
        "the six exact legacy public redirects changed unexpectedly",
    )
    _require(
        public_redirects["migration_mode"] == "atomic_route_change"
        and not public_redirects["traffic_split_steps_percent"],
        "public redirects require one atomic route change",
    )
    for group in (public_static, public_website, public_redirects):
        _require(
            group.get("handoff_group") == "public_website",
            "static files, catalog JSON, and redirects must share one handoff group",
        )
    _require(
        all(kind == "exact" for kind, _ in _paths(public_static))
        and ("exact", "/public/apps.json") not in _paths(public_static),
        "only exact built static objects may move; the dynamic catalog stays separate",
    )

    candidate = routes["candidate_maps"]["parallel_candidate"]
    _require(
        set(candidate["route_group_ids"])
        == {
            "catalog_api_reads",
            "media_api_reads",
            "state_api",
            "new_screenshot_assets",
            "legacy_media_download",
            "public_static_site",
            "public_website_catalog",
            "public_redirects",
        },
        "parallel candidate route group closure changed",
    )
    _require(
        routes["candidate_maps"]["admin_candidate"]["route_group_ids"]
        == ["new_admin"],
        "admin candidate route group changed",
    )
    production = routes["candidate_maps"]["production_initial"]
    _require(production["default_backend"] == "app_engine_default", "initial production changed")
    _require(not production["route_group_ids"], "initial production must have no route groups")


def validate_thresholds(thresholds: dict[str, Any]) -> None:
    _require(thresholds.get("schema_version") == 1, "unsupported threshold schema")
    comparison = thresholds["comparison"]
    _require(comparison["schedule_seconds"] <= 3600, "comparison must run at least hourly")
    _require(
        comparison["minimum_consecutive_zero_diff_reports"] >= 3,
        "at least three consecutive zero-diff reports are required",
    )
    _require(
        comparison["material_fix_restarts_evidence_streak"] is True,
        "material fixes must restart the comparison evidence streak",
    )
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

    cutover = thresholds["cutover"]
    _require(
        cutover["mode"]
        == "single_atomic_switch_after_parallel_parity_and_operator_approval",
        "cutover mode changed unexpectedly",
    )
    _require(cutover["percentage_canaries_enabled"] is False, "canaries must be disabled")
    _require(cutover["minimum_observation_hours"] == 0, "fixed wait must remain disabled")
    _require(
        cutover["require_complete_comparator_before_cutover"] is True,
        "cutover requires the complete comparator",
    )
    _require(
        cutover["require_full_public_transport_parity_before_cutover"] is True,
        "cutover requires full public HTTP/HTTPS parity",
    )
    _require(
        cutover["require_app_engine_fallback_parity_before_cutover"] is True,
        "cutover requires App Engine fallback parity",
    )
    _require(
        cutover["require_native_port_80_smoke_before_cutover"] is True,
        "cutover requires a native port-80 smoke",
    )
    _require(cutover["state_split_traffic_allowed"] is False, "state cannot be split")
    _require(
        cutover["admin_writer_split_traffic_allowed"] is False,
        "admin writers cannot be split",
    )
    _require(
        thresholds["post_cutover"] == {
            "fixed_minimum_wait_required": False,
            "continue_comparator": True,
            "immediate_rollback_on_gate_failure": True,
        },
        "post-cutover policy changed unexpectedly",
    )
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


def validate_public_candidate(candidate: dict[str, Any], routes: dict[str, Any]) -> None:
    _require(candidate.get("schema_version") == 1, "unsupported candidate baseline schema")
    _require(
        candidate.get("status") == "deployed_pre_dns_domain_move_pending",
        "public candidate baseline status changed unexpectedly",
    )
    _require(candidate.get("project") == "trs-80", "candidate project changed")
    _require(candidate.get("production_changed") is False, "production must stay unchanged")
    _require(candidate["dns"]["records_created"] is False, "candidate DNS is not yet authorized")
    _require(
        set(candidate["dns"]["authoritative_nameservers"])
        == {"curt.ns.cloudflare.com", "rita.ns.cloudflare.com"},
        "recorded authoritative DNS provider changed",
    )
    records = candidate["dns"]["required_records"]
    _require(
        set(records) == {"next.retrostore.org", "admin-next.retrostore.org"},
        "candidate DNS names changed",
    )
    _require(
        {entry["A"] for entry in records.values()} == {"34.102.211.182"}
        and {entry["AAAA"] for entry in records.values()} == {"2600:1901:0:81dc::"},
        "candidate DNS addresses changed",
    )
    cloud_run = candidate["cloud_run"]
    _require(
        cloud_run["api"]["service"] == routes["backends"]["cloud_run_api"]["service"]
        and cloud_run["admin"]["service"]
        == routes["backends"]["cloud_run_admin"]["service"],
        "candidate Cloud Run baseline differs from route plan",
    )
    for service in cloud_run.values():
        _require(
            service["ingress"] == "internal-and-cloud-load-balancing"
            and service["default_url_disabled"] is True
            and service["public_invoker"] is True
            and "@trs-80.iam.gserviceaccount.com" in service["service_account"],
            "candidate Cloud Run exposure boundary changed",
        )
    static = candidate["static_site"]
    _require(
        static["bucket"] == routes["backends"]["static_backend_bucket"]["bucket"]
        and static["object_count"] == 78
        and static["cdn_enabled"] is False
        and static["cache_control"] == "no-store"
        and static["access_control_allow_origin"] == "*",
        "candidate static-site baseline changed",
    )
    parity = candidate["pre_dns_http_parity"]
    _require(
        parity["total_scenarios"] == parity["matching_scenarios"] == 350
        and parity["passes"] is True,
        "candidate pre-DNS parity baseline is not green",
    )
    state = candidate["pre_dns_synthetic_state_lifecycle"]
    _require(
        state["protobuf_bytes"] == 34
        and state["upload_success"] is True
        and state["download_round_trip_match"] is True
        and state["exclude_memory_data_match"] is True
        and state["overlap_region_match"] is True
        and state["contains_state_token"] is False
        and state["passes"] is True,
        "candidate pre-DNS synthetic state lifecycle is not green",
    )
    clients = candidate["pre_dns_real_clients"]
    _require(
        clients["reviewed_trs80_revision"]
        == "aecbddcc7f5515fb844bb7a1fc350d8ffaaf5ce5"
        and clients["published_jvm_sdk_method_count"] == 9
        and clients["trs80_kmp_method_count"] == 5
        and clients["trs80_embedded_c_method_count"] == 3
        and clients["contains_state_tokens_or_payloads"] is False
        and clients["passes"] is True,
        "candidate pre-DNS real-client gate is not green",
    )
    _require(
        candidate["load_balancer"]["default_backend"] == "retrostore-appengine-default",
        "candidate load balancer must fail closed to App Engine",
    )


def main() -> int:
    routes = _load(ROUTES_PATH)
    validate_routes(routes)
    validate_thresholds(_load(THRESHOLDS_PATH))
    validate_private_soak(_load(PRIVATE_SOAK_PATH))
    validate_public_candidate(_load(PUBLIC_CANDIDATE_PATH), routes)
    print("front-door route, threshold, and candidate baselines: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

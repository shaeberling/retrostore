"""Verify a static-site bundle and emit a non-executable deployment plan."""

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

_PUBLIC_BUCKET_NAME = "trs-80-retrostore-public"
_PROTECTED_BUCKETS = frozenset(
    {
        "trs-80-retrostore-assets",
        "trs-80-retrostore-state",
        "trs-80.appspot.com",
        "staging.trs-80.appspot.com",
        "us.artifacts.trs-80.appspot.com",
    }
)


def plan_public_site_deployment(
    bundle: Path,
    build_report: Mapping[str, Any],
    *,
    target_bucket: str,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Create a checksum-closed plan with no cloud mutation capability."""
    now = generated_at or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")
    bundle = bundle.resolve()
    _validate_target_bucket(target_bucket)
    objects, aggregate_sha256, total_bytes = _verify_bundle(bundle, build_report)
    return {
        "schema_version": 1,
        "generated_at": now.astimezone(UTC).isoformat(),
        "operation": "plan_static_public_website_deployment",
        "applied": False,
        "production_changed": False,
        "bundle": str(bundle),
        "source_build_aggregate_sha256": aggregate_sha256,
        "target": {
            "project": "trs-80",
            "bucket": target_bucket,
            "required_state": "must_not_exist",
            "required_location": "us-central1",
            "dedicated_public_site_bucket": True,
            "uniform_bucket_level_access": True,
            "website": {
                "main_page_suffix": "index.html",
                "not_found_page": None,
            },
        },
        "proposed_initial_policy": {
            "status": "approved_simple_hobby_project_policy",
            "deployment_strategy": "single_dedicated_bucket",
            "handoff_strategy": "atomic_url_map_backend_switch",
            "root_request_resolution": "cloud_storage_main_page_suffix",
            "missing_object_policy": "native_cloud_storage_404",
            "public_access_prevention": "disabled_for_dedicated_public_site_bucket",
            "bucket_iam": "roles/storage.objectViewer for allUsers",
            "cdn_enabled": False,
            "cache_control": "no-store",
            "future_optional_optimization": (
                "Enable Cloud CDN later only if measured traffic or latency justifies it."
            ),
            "reason": (
                "This small public static site does not initially need CDN or "
                "private-origin machinery; keep application data in separate "
                "private buckets."
            ),
        },
        "front_door": {
            "status": "approved_candidate_only",
            "default_backend": "app_engine_default",
            "static_backend": "static_backend_bucket",
            "static_matches": {
                "kind": "exact_only",
                "paths": ["/", *(f"/{item['object']}" for item in objects)],
                "prefixes": [],
            },
            "atomic_companions": [
                "cloud_run_api:/public/apps.json",
                "cloud_run_api:/community[/]",
                "cloud_run_api:/rsc[/]",
                "cloud_run_api:/app[/]",
            ],
            "unknown_path_disposition": "app_engine_default",
        },
        "required_external_approvals": [],
        "operations": {
            "uploads": [
                {
                    **item,
                    "if_generation_match": 0,
                    "cache_control": "no-store",
                }
                for item in objects
            ],
            "deletes": [],
        },
        "result": {
            "object_count": len(objects),
            "total_bytes": total_bytes,
            "delete_count": 0,
            "ready_to_apply": False,
        },
        "safety": {
            "cloud_requests_made": False,
            "apply_capability_present": False,
            "existing_bucket_targets_rejected": True,
            "create_only_object_preconditions": True,
            "contains_file_bodies": False,
            "contains_credentials": False,
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--build-report", type=Path, required=True)
    parser.add_argument("--target-bucket", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    report = _load_json_object(args.build_report)
    plan = plan_public_site_deployment(
        args.bundle,
        report,
        target_bucket=args.target_bucket,
    )
    if args.output.exists():
        raise FileExistsError(f"Deployment plan already exists: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "applied": False,
                "object_count": plan["result"]["object_count"],
                "ready_to_apply": False,
                "target_bucket": args.target_bucket,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


def _validate_target_bucket(target_bucket: str) -> None:
    if target_bucket in _PROTECTED_BUCKETS:
        raise ValueError("Static website planning refuses an existing protected bucket")
    if target_bucket != _PUBLIC_BUCKET_NAME:
        raise ValueError(f"Target bucket must be exactly {_PUBLIC_BUCKET_NAME}")


def _verify_bundle(
    bundle: Path, build_report: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], str, int]:
    if not bundle.is_dir():
        raise FileNotFoundError(f"Static website bundle is missing: {bundle}")
    if (
        build_report.get("schema_version") != 1
        or build_report.get("operation") != "build_static_public_website"
        or build_report.get("applied") is not True
        or build_report.get("production_changed") is not False
    ):
        raise ValueError("Build report is not an applied local static-site build")
    try:
        report_output = Path(build_report["output"]).resolve()
    except (KeyError, TypeError) as error:
        raise ValueError("Build report output is invalid") from error
    if report_output != bundle:
        raise ValueError("Build report output does not match the selected bundle")

    manifest = build_report.get("objects")
    result = build_report.get("result")
    if not isinstance(manifest, list) or not isinstance(result, dict):
        raise ValueError("Build report manifest is missing")
    actual_paths = sorted(
        path.relative_to(bundle).as_posix()
        for path in bundle.rglob("*")
        if path.is_file()
    )
    expected_paths: list[str] = []
    aggregate = hashlib.sha256()
    total_bytes = 0
    verified = []
    for item in manifest:
        if not isinstance(item, dict):
            raise ValueError("Build report object is invalid")
        path = item.get("path")
        relative = PurePosixPath(path) if isinstance(path, str) else PurePosixPath("..")
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise ValueError("Build report contains an unsafe object path")
        if path in expected_paths:
            raise ValueError(f"Build report contains duplicate object path: {path}")
        expected_paths.append(path)
        body = bundle.joinpath(*relative.parts).read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        if item.get("size") != len(body) or item.get("sha256") != digest:
            raise ValueError(f"Static object differs from build report: {path}")
        content_type = item.get("content_type")
        if not isinstance(content_type, str) or not content_type:
            raise ValueError(f"Static object has no content type: {path}")
        encoded_path = path.encode()
        aggregate.update(len(encoded_path).to_bytes(8, "big"))
        aggregate.update(encoded_path)
        aggregate.update(len(body).to_bytes(8, "big"))
        aggregate.update(bytes.fromhex(digest))
        total_bytes += len(body)
        verified.append(
            {
                "source": path,
                "object": path,
                "size": len(body),
                "sha256": digest,
                "content_type": content_type,
            }
        )
    if sorted(expected_paths) != actual_paths:
        raise ValueError("Static bundle and build-report object sets differ")
    aggregate_sha256 = aggregate.hexdigest()
    if (
        result.get("file_count") != len(verified)
        or result.get("total_bytes") != total_bytes
        or result.get("content_aggregate_sha256") != aggregate_sha256
    ):
        raise ValueError("Build report aggregate does not match the verified bundle")
    return verified, aggregate_sha256, total_bytes


def _load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


if __name__ == "__main__":
    raise SystemExit(main())

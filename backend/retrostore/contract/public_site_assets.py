"""Compare the complete local static website bundle with the live legacy files."""

import argparse
import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import httpx

from retrostore.public_site import (
    _FAVICON_SOURCE,
    _GFX_SOURCE,
    _PUBLIC_SOURCE,
    legacy_static_content_type,
    transform_public_site_text,
)

_MAX_FILE_BYTES = 5 * 1024 * 1024
_TRANSFORMED_FILENAMES = frozenset({"apps.html", "contact.html", "signup.html"})


def compare_public_site_bundle(
    reference: httpx.Client,
    candidate_root: Path,
    *,
    reference_url: str,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    now = generated_at or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")
    if not candidate_root.is_dir():
        raise FileNotFoundError(f"Static candidate bundle is missing: {candidate_root}")

    candidate_files = sorted(
        path.relative_to(candidate_root).as_posix()
        for path in candidate_root.rglob("*")
        if path.is_file()
    )
    if not candidate_files:
        raise ValueError("Static candidate bundle is empty")
    scenarios = [("/", "index.html"), *[(f"/{path}", path) for path in candidate_files]]
    results = []
    for request_path, object_path in scenarios:
        source = _legacy_source_bytes(object_path)
        candidate = (candidate_root / object_path).read_bytes()
        expected_candidate, transformed = _expected_candidate_bytes(object_path, source)
        response = reference.get(request_path)
        if len(response.content) > _MAX_FILE_BYTES:
            raise ValueError(f"Legacy static response exceeds limit: {request_path}")
        expected_content_type = legacy_static_content_type(object_path)
        checks = {
            "reference_status": response.status_code == 200,
            "reference_content_type": (
                response.headers.get("content-type", "").partition(";")[0].casefold()
                == expected_content_type
            ),
            "reference_cors": response.headers.get("access-control-allow-origin") == "*",
            "reference_matches_source": response.content == source,
            "candidate_matches_expected": candidate == expected_candidate,
        }
        results.append(
            {
                "path": request_path,
                "object_path": object_path,
                "intentional_transformation": transformed,
                "passes": all(checks.values()),
                "checks": checks,
                "reference_bytes": len(response.content),
                "candidate_bytes": len(candidate),
                "reference_sha256": hashlib.sha256(response.content).hexdigest(),
                "candidate_sha256": hashlib.sha256(candidate).hexdigest(),
                "content_type": expected_content_type,
            }
        )

    differences = [
        {
            "path": result["path"],
            "failed_checks": sorted(
                name for name, passes in result["checks"].items() if not passes
            ),
        }
        for result in results
        if not result["passes"]
    ]
    matching = len(results) - len(differences)
    return {
        "schema_version": 1,
        "generated_at": now.astimezone(UTC).isoformat(),
        "kind": "retrostore_public_static_bundle_comparison",
        "reference_url": reference_url,
        "candidate": str(candidate_root.resolve()),
        "safety": {
            "read_only": True,
            "contains_file_bodies": False,
            "contains_credentials": False,
            "contains_catalog_values": False,
            "production_changed": False,
        },
        "scope": {
            "object_count": len(candidate_files),
            "scenario_count": len(results),
            "intentional_transformation_count": sum(
                result["intentional_transformation"] for result in results
            ),
        },
        "summary": {
            "total": len(results),
            "matching": matching,
            "different": len(differences),
            "passes": not differences,
        },
        "differences": differences,
        "results": results,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-url", required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args(argv)
    if args.reference_url.rstrip("/") != "https://retrostore.org":
        raise ValueError("--reference-url must be exactly https://retrostore.org")
    with httpx.Client(
        base_url=args.reference_url,
        follow_redirects=False,
        timeout=args.timeout_seconds,
    ) as reference:
        report = compare_public_site_bundle(
            reference,
            args.candidate_root,
            reference_url=args.reference_url,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"scope": report["scope"], "summary": report["summary"]}))
    return 0 if report["summary"]["passes"] else 1


def _legacy_source_bytes(object_path: str) -> bytes:
    relative = PurePosixPath(object_path)
    parts = relative.parts
    if not parts or relative.is_absolute() or ".." in parts:
        raise ValueError(f"Unsafe static object path: {object_path}")
    if parts[0] == "public":
        source = _PUBLIC_SOURCE.joinpath(*parts[1:])
    elif parts[0] == "favicon":
        source = _FAVICON_SOURCE.joinpath(*parts[1:])
    elif parts[0] == "gfx":
        source = _GFX_SOURCE.joinpath(*parts[1:])
    elif object_path == "favicon.ico":
        source = _FAVICON_SOURCE / "favicon.ico"
    else:
        source = _PUBLIC_SOURCE.joinpath(*parts)
    if not source.is_file():
        raise ValueError(f"Static candidate has no legacy source: {object_path}")
    return source.read_bytes()


def _expected_candidate_bytes(object_path: str, source: bytes) -> tuple[bytes, bool]:
    filename = PurePosixPath(object_path).name
    in_public_tree = not object_path.startswith(("favicon/", "gfx/"))
    if in_public_tree and filename in _TRANSFORMED_FILENAMES:
        transformed, _ = transform_public_site_text(filename, source.decode())
        return transformed.encode(), True
    return source, False


if __name__ == "__main__":
    raise SystemExit(main())

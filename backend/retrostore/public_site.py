"""Build and validate the static RetroStore website without deploying it."""

import argparse
import hashlib
import json
import os
import shutil
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_PUBLIC_SOURCE = _REPOSITORY_ROOT / "appengine/src/main/webapp/WEB-INF/public"
_FAVICON_SOURCE = _REPOSITORY_ROOT / "appengine/src/main/webapp/WEB-INF/favicon"
_GFX_SOURCE = _REPOSITORY_ROOT / "appengine/src/main/webapp/WEB-INF/gfx"
_STATIC_SUFFIXES = frozenset({".css", ".gif", ".ico", ".js", ".json", ".png", ".svg"})
_REMOVED_MISSING_SCRIPT = '    <script src="js/contact_me.js"></script>\n'


class _ReferenceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.references: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        for name, value in attrs:
            if value is not None and name in {"href", "src"}:
                self.references.append(value)


def build_public_site(
    output: Path,
    *,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    now = generated_at or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")
    if output.exists():
        raise FileExistsError(f"Static website output already exists: {output}")
    for source in (_PUBLIC_SOURCE, _FAVICON_SOURCE, _GFX_SOURCE):
        if not source.is_dir():
            raise FileNotFoundError(f"Static website source is missing: {source}")

    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(_PUBLIC_SOURCE, output)
        shutil.copytree(_FAVICON_SOURCE, output / "favicon")
        shutil.copytree(_GFX_SOURCE, output / "gfx")
        shutil.copy2(_FAVICON_SOURCE / "favicon.ico", output / "favicon.ico")
        transformations = _transform_candidate_files(output)
        missing = _missing_static_references(output)
        if missing:
            raise ValueError(
                "Static website has missing local assets: " + ", ".join(missing)
            )
        files = sorted(path for path in output.rglob("*") if path.is_file())
        aggregate = hashlib.sha256()
        total_bytes = 0
        for path in files:
            relative = path.relative_to(output).as_posix()
            body = path.read_bytes()
            total_bytes += len(body)
            encoded_path = relative.encode()
            aggregate.update(len(encoded_path).to_bytes(8, "big"))
            aggregate.update(encoded_path)
            aggregate.update(len(body).to_bytes(8, "big"))
            aggregate.update(hashlib.sha256(body).digest())
    except BaseException:
        if output.is_dir():
            shutil.rmtree(output)
        raise

    return {
        "schema_version": 1,
        "generated_at": now.astimezone(UTC).isoformat(),
        "operation": "build_static_public_website",
        "applied": True,
        "production_changed": False,
        "source": "appengine/src/main/webapp/WEB-INF/public",
        "output": str(output.resolve()),
        "safety": {
            "contains_credentials": False,
            "contains_private_catalog_data": False,
            "deploys_resources": False,
        },
        "transformations": transformations,
        "result": {
            "file_count": len(files),
            "total_bytes": total_bytes,
            "content_aggregate_sha256": aggregate.hexdigest(),
            "missing_static_reference_count": 0,
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-output")
    args = parser.parse_args(argv)

    expected_confirmation = str(args.output.resolve())
    if not args.apply:
        report: Mapping[str, Any] = {
            "schema_version": 1,
            "operation": "build_static_public_website",
            "applied": False,
            "production_changed": False,
            "source": str(_PUBLIC_SOURCE),
            "output": expected_confirmation,
        }
    else:
        if (
            args.confirm_output is None
            or Path(args.confirm_output).resolve() != args.output.resolve()
        ):
            raise ValueError("--confirm-output must be the exact resolved output path")
        report = build_public_site(args.output)

    _write_create_only_json(args.report, report)
    print(
        json.dumps(
            {
                "applied": report["applied"],
                "output": report["output"],
                "result": report.get("result"),
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


def _transform_candidate_files(output: Path) -> dict[str, int]:
    apps = output / "apps.html"
    apps_body = apps.read_text()
    old_rpc = '$.get("/rpc?m=pubapplist", function(apps) {'
    new_rpc = '$.get("/public/apps.json", function(apps) {'
    if apps_body.count(old_rpc) != 1:
        raise ValueError("Legacy public app-list fetch changed unexpectedly")
    if apps_body.count("/public/lightbox2/") != 2:
        raise ValueError("Legacy public lightbox paths changed unexpectedly")
    apps.write_text(
        apps_body.replace(old_rpc, new_rpc).replace(
            "/public/lightbox2/", "/lightbox2/"
        )
    )

    removed_scripts = 0
    for filename in ("contact.html", "signup.html"):
        path = output / filename
        body = path.read_text()
        count = body.count(_REMOVED_MISSING_SCRIPT)
        if count != 1:
            raise ValueError(f"{filename} missing-script marker changed unexpectedly")
        path.write_text(body.replace(_REMOVED_MISSING_SCRIPT, ""))
        removed_scripts += count
    return {
        "public_app_list_fetch_rewritten": 1,
        "lightbox_paths_rewritten": 2,
        "missing_contact_scripts_removed": removed_scripts,
    }


def _missing_static_references(root: Path) -> list[str]:
    missing: set[str] = set()
    for html in sorted(root.rglob("*.html")):
        parser = _ReferenceParser()
        parser.feed(html.read_text())
        relative_parent = PurePosixPath(html.relative_to(root).as_posix()).parent
        for value in parser.references:
            path = _static_reference_path(value, relative_parent)
            if path is not None and not (root / path).is_file():
                missing.add(f"{html.relative_to(root).as_posix()} -> {path.as_posix()}")
    return sorted(missing)


def _static_reference_path(
    value: str, relative_parent: PurePosixPath
) -> PurePosixPath | None:
    if not value or value.startswith(("#", "//", "data:", "mailto:")):
        return None
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or "'" in parsed.path or '"' in parsed.path:
        return None
    candidate = PurePosixPath(parsed.path.lstrip("/"))
    if not parsed.path.startswith("/"):
        candidate = relative_parent / candidate
    if candidate.suffix.lower() not in _STATIC_SUFFIXES:
        return None
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("Static website reference escapes the bundle")
    return candidate


def _write_create_only_json(path: Path, value: Mapping[str, Any]) -> None:
    body = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(body)


if __name__ == "__main__":
    raise SystemExit(main())

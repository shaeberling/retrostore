"""Validate a normalized catalog export and print a non-sensitive summary."""

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from retrostore.mirror import load_catalog_mirror_archive


def build_verification_report(path: Path) -> dict[str, Any]:
    """Load and fully verify an export archive, returning aggregate metadata only."""

    mirror = load_catalog_mirror_archive(path)
    archive_sha256 = hashlib.sha256()
    with path.open("rb") as archive:
        while chunk := archive.read(1024 * 1024):
            archive_sha256.update(chunk)

    return {
        "schema_version": 1,
        "verified": True,
        "source_project_id": mirror.source_project_id,
        "exported_at": mirror.exported_at,
        "high_water_mark": mirror.high_water_mark,
        "app_count": len(mirror.apps),
        "media_count": len(mirror.media),
        "screenshot_count": len(mirror.screenshots),
        "object_count": len(mirror.object_bytes),
        "object_bytes": sum(len(body) for body in mirror.object_bytes.values()),
        "archive_bytes": path.stat().st_size,
        "archive_sha256": archive_sha256.hexdigest(),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="Path to the catalog export ZIP")
    args = parser.parse_args(argv)
    report = build_verification_report(args.archive)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

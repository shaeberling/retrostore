import hashlib
import json
from pathlib import Path

import pytest

from retrostore.mirror.verify_archive import build_verification_report, main
from tests.mirror.test_archive import _write_archive


def test_builds_aggregate_report_after_full_archive_verification(tmp_path: Path) -> None:
    path = tmp_path / "catalog.zip"
    _write_archive(path)

    report = build_verification_report(path)

    assert report == {
        "schema_version": 1,
        "verified": True,
        "source_project_id": "trs-80",
        "exported_at": "2026-08-06T20:00:00Z",
        "high_water_mark": "2026-08-06T19:59:59.999Z",
        "app_count": 1,
        "media_count": 2,
        "screenshot_count": 1,
        "object_count": 3,
        "object_bytes": len(b"disk image") + len(b"command image") + len(b"screenshot"),
        "archive_bytes": path.stat().st_size,
        "archive_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def test_command_prints_compact_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "catalog.zip"
    _write_archive(path)

    assert main([str(path)]) == 0

    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["verified"] is True
    assert report["object_count"] == 3

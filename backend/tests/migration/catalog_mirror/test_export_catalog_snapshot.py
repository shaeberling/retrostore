import json
from pathlib import Path

import pytest

import retrostore.migration.catalog_mirror.export_catalog_snapshot as export_command
from retrostore.migration.catalog_mirror import build_catalog_snapshot, load_catalog_mirror_archive
from tests.migration.catalog_mirror.test_persistence import (
    MemoryObjectStore,
    MemorySnapshotStore,
    _mirror,
)


def test_exports_one_exact_staged_snapshot_and_round_trips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    objects = MemoryObjectStore()
    snapshots = MemorySnapshotStore()
    mirror = _mirror(name="Staged")
    snapshot = build_catalog_snapshot(mirror)
    for value in snapshot.objects:
        objects.put_verified(value)
    snapshots.stage(snapshot)
    monkeypatch.setattr(
        export_command,
        "google_catalog_stores",
        lambda **kwargs: (objects, snapshots),
    )
    archive = tmp_path / "snapshot.zip"
    report_path = tmp_path / "report.json"

    assert (
        export_command.main(
            [
                "--project",
                "trs-80",
                "--database",
                "retrostore",
                "--bucket",
                "trs-80-retrostore-assets",
                "--snapshot-id",
                snapshot.id,
                "--manifest-sha256",
                snapshot.manifest_sha256,
                "--output-archive",
                str(archive),
                "--output-report",
                str(report_path),
                "--impersonate-service-account",
                "retrostore-migrator@trs-80.iam.gserviceaccount.com",
            ]
        )
        == 0
    )

    report = json.loads(report_path.read_text())
    assert report["read_only"] is True
    assert report["snapshot_id"] == snapshot.id
    assert report["counts"] == {
        "apps": 1,
        "media": 2,
        "object_bytes": 33,
        "objects": 3,
        "screenshots": 1,
    }
    assert load_catalog_mirror_archive(archive).to_dict() == mirror.to_dict()


def test_rejects_an_inexact_requested_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    objects = MemoryObjectStore()
    snapshots = MemorySnapshotStore()
    snapshot = build_catalog_snapshot(_mirror())
    for value in snapshot.objects:
        objects.put_verified(value)
    snapshots.stage(snapshot)
    monkeypatch.setattr(
        export_command,
        "google_catalog_stores",
        lambda **kwargs: (objects, snapshots),
    )

    with pytest.raises(ValueError, match="digest"):
        export_command.main(
            [
                "--project",
                "trs-80",
                "--database",
                "retrostore",
                "--bucket",
                "trs-80-retrostore-assets",
                "--snapshot-id",
                snapshot.id,
                "--manifest-sha256",
                "0" * 64,
                "--output-archive",
                str(tmp_path / "snapshot.zip"),
                "--output-report",
                str(tmp_path / "report.json"),
                "--impersonate-service-account",
                "retrostore-migrator@trs-80.iam.gserviceaccount.com",
            ]
        )

    assert not (tmp_path / "snapshot.zip").exists()

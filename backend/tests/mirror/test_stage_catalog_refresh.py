import json
from pathlib import Path

import pytest

import retrostore.mirror.stage_catalog_refresh as refresh_command
from retrostore.mirror import build_catalog_snapshot, import_catalog_mirror
from tests.mirror.test_archive import _write_archive
from tests.mirror.test_catalog import _manifest
from tests.mirror.test_persistence import MemoryObjectStore, MemorySnapshotStore, _mirror


def _arguments(archive: Path, output: Path) -> list[str]:
    return [
        str(archive),
        "--project",
        "trs-80",
        "--database",
        "retrostore",
        "--bucket",
        "trs-80-retrostore-assets",
        "--output",
        str(output),
    ]


def _changed_archive(path: Path) -> None:
    manifest = _manifest()
    manifest["apps"][0]["name"] = "Changed"  # type: ignore[index]
    manifest["source"]["high_water_mark"] = "refresh-2"  # type: ignore[index]
    _write_archive(path, manifest=manifest)


def test_dry_run_reports_id_only_changes_without_cloud_clients(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline = tmp_path / "baseline.zip"
    candidate = tmp_path / "candidate.zip"
    output = tmp_path / "report.json"
    _write_archive(baseline)
    _changed_archive(candidate)
    monkeypatch.setattr(
        refresh_command,
        "google_catalog_stores",
        lambda **kwargs: pytest.fail(f"constructed cloud clients: {kwargs}"),
    )

    assert refresh_command.main(
        [*_arguments(candidate, output), "--baseline-archive", str(baseline)]
    ) == 0

    report = json.loads(output.read_text())
    assert report["applied"] is False
    assert report["activation_available"] is False
    assert report["changes"]["apps"] == {
        "added_count": 0,
        "added_ids": [],
        "changed_count": 1,
        "changed_ids": ["app-1"],
        "removed_count": 0,
        "removed_ids": [],
    }
    assert "publisher@example.test" not in output.read_text()


def test_apply_requires_exact_active_expectation_before_cloud_clients(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "candidate.zip"
    _write_archive(archive)
    called = False

    def unexpected_clients(**kwargs: str) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(refresh_command, "google_catalog_stores", unexpected_clients)

    with pytest.raises(ValueError, match="expected active snapshot"):
        refresh_command.main(
            [
                *_arguments(archive, tmp_path / "report.json"),
                "--apply-stage",
                "--confirm-project",
                "trs-80",
                "--impersonate-service-account",
                "retrostore-migrator@trs-80.iam.gserviceaccount.com",
            ]
        )

    assert called is False


def test_apply_stages_changed_snapshot_and_proves_active_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "candidate.zip"
    output = tmp_path / "report.json"
    _changed_archive(archive)
    objects = MemoryObjectStore()
    snapshots = MemorySnapshotStore()
    active = import_catalog_mirror(_mirror(), objects, snapshots)
    monkeypatch.setattr(
        refresh_command,
        "google_catalog_stores",
        lambda **kwargs: (objects, snapshots),
    )

    assert refresh_command.main(
        [
            *_arguments(archive, output),
            "--apply-stage",
            "--confirm-project",
            "trs-80",
            "--impersonate-service-account",
            "retrostore-migrator@trs-80.iam.gserviceaccount.com",
            "--expected-active-snapshot-id",
            active.snapshot_id,
            "--expected-active-manifest-sha256",
            active.manifest_sha256,
        ]
    ) == 0

    report = json.loads(output.read_text())
    candidate = build_catalog_snapshot(refresh_command.load_catalog_mirror_archive(archive))
    assert report["applied"] is True
    assert report["activation_available"] is False
    assert report["active_pointer_unchanged"] is True
    assert report["candidate_matches_active"] is False
    assert report["stage"]["snapshot_id"] == candidate.id
    assert snapshots.active_id == active.snapshot_id
    assert candidate.id in snapshots.snapshots

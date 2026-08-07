import json
from pathlib import Path

import pytest

import retrostore.mirror.import_catalog as import_command
from retrostore.mirror.google_cloud import validate_catalog_target
from tests.mirror.test_archive import _write_archive
from tests.mirror.test_persistence import MemoryObjectStore, MemorySnapshotStore


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


def test_dry_run_validates_archive_without_constructing_cloud_clients(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = tmp_path / "catalog.zip"
    output = tmp_path / "report.json"
    _write_archive(archive)

    def unexpected_cloud_clients(**kwargs: str) -> None:
        raise AssertionError(f"dry run constructed cloud clients: {kwargs}")

    monkeypatch.setattr(import_command, "google_catalog_stores", unexpected_cloud_clients)

    assert import_command.main(_arguments(archive, output)) == 0

    report = json.loads(output.read_text())
    assert report["applied"] is False
    assert report["target"] == {
        "project": "trs-80",
        "database": "retrostore",
        "bucket": "trs-80-retrostore-assets",
    }
    assert report["object_count"] == 3
    assert json.loads(capsys.readouterr().out) == report


def test_apply_requires_exact_confirmation_before_constructing_clients(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "catalog.zip"
    _write_archive(archive)
    arguments = [*_arguments(archive, tmp_path / "report.json"), "--apply"]
    called = False

    def unexpected_cloud_clients(**kwargs: str) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(import_command, "google_catalog_stores", unexpected_cloud_clients)

    with pytest.raises(ValueError, match="confirm-project"):
        import_command.main(arguments)

    assert called is False


def test_apply_imports_through_injected_stores_and_reports_reconciliation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "catalog.zip"
    output = tmp_path / "report.json"
    _write_archive(archive)
    objects = MemoryObjectStore()
    snapshots = MemorySnapshotStore()
    monkeypatch.setattr(
        import_command,
        "google_catalog_stores",
        lambda **kwargs: (objects, snapshots),
    )

    assert import_command.main(
        [
            *_arguments(archive, output),
            "--apply",
            "--confirm-project",
            "trs-80",
            "--impersonate-service-account",
            "retrostore-migrator@trs-80.iam.gserviceaccount.com",
        ]
    ) == 0

    report = json.loads(output.read_text())
    assert report["applied"] is True
    assert report["object_count"] == 3
    assert report["objects_created"] == 3
    assert report["service_account"] == (
        "retrostore-migrator@trs-80.iam.gserviceaccount.com"
    )
    assert snapshots.active_id == report["snapshot_id"]


def test_apply_requires_the_dedicated_migration_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "catalog.zip"
    _write_archive(archive)
    called = False

    def unexpected_cloud_clients(**kwargs: str) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(import_command, "google_catalog_stores", unexpected_cloud_clients)
    arguments = [
        *_arguments(archive, tmp_path / "report.json"),
        "--apply",
        "--confirm-project",
        "trs-80",
        "--impersonate-service-account",
        "some-editor@trs-80.iam.gserviceaccount.com",
    ]

    with pytest.raises(ValueError, match="dedicated project migration identity"):
        import_command.main(arguments)

    assert called is False


def test_rejects_legacy_or_implicit_cloud_targets() -> None:
    with pytest.raises(ValueError, match="default database"):
        validate_catalog_target(project="trs-80", database="(default)", bucket="safe")
    with pytest.raises(ValueError, match="legacy bucket"):
        validate_catalog_target(
            project="trs-80",
            database="retrostore",
            bucket="trs-80.appspot.com",
        )
    with pytest.raises(ValueError, match="must be explicit"):
        validate_catalog_target(project="", database="retrostore", bucket="safe")

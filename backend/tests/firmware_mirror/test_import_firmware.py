import json
from pathlib import Path

import pytest

import retrostore.firmware_mirror.import_firmware as import_command
from tests.firmware_mirror.test_model import _archive, _fixture
from tests.firmware_mirror.test_persistence import FakeObjectStore, FakeSnapshotStore


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


def _write_archive(path: Path) -> None:
    manifest, objects = _fixture()
    _archive(path, manifest, objects)


def test_dry_run_validates_without_constructing_cloud_clients(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = tmp_path / "firmware.zip"
    output = tmp_path / "report.json"
    _write_archive(archive)

    def unexpected_cloud_clients(**kwargs: str) -> None:
        raise AssertionError(f"dry run constructed cloud clients: {kwargs}")

    monkeypatch.setattr(
        import_command, "google_firmware_stores", unexpected_cloud_clients
    )

    assert import_command.main(_arguments(archive, output)) == 0

    report = json.loads(output.read_text())
    assert report["applied"] is False
    assert report["firmware_count"] == 3
    assert report["object_count"] == 3
    assert json.loads(capsys.readouterr().out) == report


def test_apply_requires_confirmation_and_dedicated_identity_before_clients(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "firmware.zip"
    _write_archive(archive)
    called = False

    def unexpected_cloud_clients(**kwargs: str) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(
        import_command, "google_firmware_stores", unexpected_cloud_clients
    )
    with pytest.raises(ValueError, match="confirm-project"):
        import_command.main(
            [*_arguments(archive, tmp_path / "first.json"), "--apply"]
        )
    with pytest.raises(ValueError, match="dedicated project migration identity"):
        import_command.main(
            [
                *_arguments(archive, tmp_path / "second.json"),
                "--apply",
                "--confirm-project",
                "trs-80",
                "--impersonate-service-account",
                "editor@trs-80.iam.gserviceaccount.com",
            ]
        )
    assert called is False


def test_apply_imports_through_guarded_injected_stores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "firmware.zip"
    output = tmp_path / "report.json"
    _write_archive(archive)
    objects = FakeObjectStore()
    snapshots = FakeSnapshotStore()
    monkeypatch.setattr(
        import_command,
        "google_firmware_stores",
        lambda **kwargs: (objects, snapshots),
    )

    assert (
        import_command.main(
            [
                *_arguments(archive, output),
                "--apply",
                "--confirm-project",
                "trs-80",
                "--impersonate-service-account",
                "retrostore-migrator@trs-80.iam.gserviceaccount.com",
            ]
        )
        == 0
    )

    report = json.loads(output.read_text())
    assert report["applied"] is True
    assert report["firmware_count"] == 3
    assert report["objects_created"] == 3
    assert report["service_account"] == (
        "retrostore-migrator@trs-80.iam.gserviceaccount.com"
    )
    assert snapshots.active == report["snapshot_id"]

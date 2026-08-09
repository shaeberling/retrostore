import json

import pytest

from retrostore.admin import stage_working_catalog
from retrostore.admin.working_catalog import build_working_catalog_materialization
from retrostore.mirror import MappingObjectReader, build_catalog_snapshot
from tests.admin.test_working_catalog import _mirror, _staged_changes
from tests.mirror.test_catalog import _reader


class FakeSnapshotStore:
    def __init__(self) -> None:
        self.staged = []

    def stage(self, snapshot) -> None:
        self.staged.append(snapshot)


def _configure(monkeypatch, *, with_changes=False):
    mirror = _mirror()
    materialization = build_working_catalog_materialization(
        mirror, build_catalog_snapshot(mirror)
    )
    snapshots = FakeSnapshotStore()
    staged, new_objects = _staged_changes() if with_changes else (
        {name: {} for name in ("apps", "authors", "media", "screenshots")},
        {},
    )
    reader = MappingObjectReader({**dict(_reader().objects), **new_objects})
    monkeypatch.setattr(
        stage_working_catalog,
        "gcloud_impersonated_credentials",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(
        stage_working_catalog,
        "google_catalog_stores",
        lambda **kwargs: (reader, snapshots),
    )
    monkeypatch.setattr(
        stage_working_catalog.firestore, "Client", lambda **kwargs: object()
    )

    class FakeWorkingStore:
        def __init__(self, client):
            pass

        def load_current(self, *, actor):
            return materialization

        def load_staged_changes(self):
            return staged

    monkeypatch.setattr(
        stage_working_catalog, "FirestoreWorkingCatalogStore", FakeWorkingStore
    )
    monkeypatch.setattr(
        stage_working_catalog,
        "load_active_catalog_mirror",
        lambda object_store, snapshot_store: mirror,
    )
    return snapshots


def _arguments(tmp_path):
    return [
        "--project",
        "trs-80",
        "--database",
        "retrostore",
        "--bucket",
        "trs-80-retrostore-assets",
        "--output",
        str(tmp_path / "report.json"),
        "--impersonate-service-account",
        "retrostore-migrator@trs-80.iam.gserviceaccount.com",
    ]


def test_dry_run_reconciles_without_staging(tmp_path, monkeypatch) -> None:
    snapshots = _configure(monkeypatch)

    result = stage_working_catalog.main(_arguments(tmp_path))

    report = json.loads((tmp_path / "report.json").read_text())
    assert result == 0
    assert report["applied"] is False
    assert report["activation_available"] is False
    assert report["candidate_matches_active"] is True
    assert report["staged_change_counts"] == {
        "apps": 0,
        "authors": 0,
        "media": 0,
        "screenshots": 0,
    }
    assert report["counts"] == {
        "apps": 1,
        "media": 2,
        "objects": 3,
        "screenshots": 1,
    }
    assert snapshots.staged == []


def test_apply_reconciles_the_ready_snapshot_without_activation(
    tmp_path, monkeypatch
) -> None:
    snapshots = _configure(monkeypatch)

    result = stage_working_catalog.main(
        [*_arguments(tmp_path), "--apply", "--confirm-project", "trs-80"]
    )

    report = json.loads((tmp_path / "report.json").read_text())
    assert result == 0
    assert report["applied"] is True
    assert report["candidate_snapshot_id"] == report["active_snapshot_id"]
    assert len(snapshots.staged) == 1


def test_apply_stages_a_new_snapshot_for_isolated_changes_without_activation(
    tmp_path, monkeypatch
) -> None:
    snapshots = _configure(monkeypatch, with_changes=True)

    result = stage_working_catalog.main(
        [*_arguments(tmp_path), "--apply", "--confirm-project", "trs-80"]
    )

    report = json.loads((tmp_path / "report.json").read_text())
    assert result == 0
    assert report["candidate_matches_active"] is False
    assert report["activation_available"] is False
    assert report["staged_change_counts"] == {
        "apps": 1,
        "authors": 1,
        "media": 1,
        "screenshots": 1,
    }
    assert report["candidate_snapshot_id"] != report["active_snapshot_id"]
    assert len(snapshots.staged) == 1


def test_apply_requires_confirmation_before_cloud_credentials(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        stage_working_catalog,
        "gcloud_impersonated_credentials",
        lambda **kwargs: pytest.fail("confirmation must precede cloud credentials"),
    )

    with pytest.raises(ValueError, match="confirm-project"):
        stage_working_catalog.main([*_arguments(tmp_path), "--apply"])

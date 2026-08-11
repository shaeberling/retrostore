import json
from types import MappingProxyType

import pytest

from retrostore.migration.admin import materialize_working_catalog
from retrostore.migration.admin.working_google_cloud import WorkingCatalogMaterializationReport


def test_dry_run_builds_the_working_plan_without_cloud_clients(tmp_path, monkeypatch) -> None:
    from tests.migration.admin.test_working_catalog import _mirror

    monkeypatch.setattr(
        materialize_working_catalog, "load_catalog_mirror_archive", lambda path: _mirror()
    )
    monkeypatch.setattr(
        materialize_working_catalog,
        "gcloud_impersonated_credentials",
        lambda **kwargs: pytest.fail("dry run must not mint credentials"),
    )
    output = tmp_path / "report.json"

    result = materialize_working_catalog.main(
        [
            str(tmp_path / "catalog.zip"),
            "--project",
            "trs-80",
            "--database",
            "retrostore",
            "--bucket",
            "trs-80-retrostore-assets",
            "--output",
            str(output),
        ]
    )

    report = json.loads(output.read_text())
    assert result == 0
    assert report["applied"] is False
    assert report["counts"] == {"apps": 1, "authors": 1, "media": 2, "screenshots": 1}
    assert report["materialization_id"].startswith("working-")


def test_apply_requires_exact_confirmation_and_migration_identity(tmp_path, monkeypatch) -> None:
    from tests.migration.admin.test_working_catalog import _mirror

    monkeypatch.setattr(
        materialize_working_catalog, "load_catalog_mirror_archive", lambda path: _mirror()
    )
    base = [
        str(tmp_path / "catalog.zip"),
        "--project",
        "trs-80",
        "--database",
        "retrostore",
        "--bucket",
        "trs-80-retrostore-assets",
        "--output",
        str(tmp_path / "report.json"),
        "--apply",
    ]

    with pytest.raises(ValueError, match="confirm-project"):
        materialize_working_catalog.main(base)
    with pytest.raises(ValueError, match="impersonate-service-account"):
        materialize_working_catalog.main([*base, "--confirm-project", "trs-80"])
    with pytest.raises(ValueError, match="dedicated project migration identity"):
        materialize_working_catalog.main(
            [
                *base,
                "--confirm-project",
                "trs-80",
                "--impersonate-service-account",
                "wrong@trs-80.iam.gserviceaccount.com",
            ]
        )


def test_apply_serializes_mapping_proxy_report(tmp_path, monkeypatch) -> None:
    from tests.migration.admin.test_working_catalog import _mirror

    mirror = _mirror()
    monkeypatch.setattr(
        materialize_working_catalog, "load_catalog_mirror_archive", lambda path: mirror
    )
    monkeypatch.setattr(
        materialize_working_catalog,
        "gcloud_impersonated_credentials",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(
        materialize_working_catalog,
        "google_catalog_stores",
        lambda **kwargs: (object(), object()),
    )
    monkeypatch.setattr(
        materialize_working_catalog,
        "load_active_catalog_mirror",
        lambda object_store, snapshot_store: mirror,
    )
    monkeypatch.setattr(materialize_working_catalog.firestore, "Client", lambda **kwargs: object())

    class FakeWorkingStore:
        def __init__(self, client):
            pass

        def materialize(self, materialization, *, actor):
            return WorkingCatalogMaterializationReport(
                materialization_id=materialization.id,
                manifest_sha256=materialization.manifest_sha256,
                counts=MappingProxyType(dict(materialization.counts)),
                documents_created=5,
                documents_reused=0,
                audit_created=True,
            )

    monkeypatch.setattr(
        materialize_working_catalog, "FirestoreWorkingCatalogStore", FakeWorkingStore
    )
    output = tmp_path / "report.json"

    result = materialize_working_catalog.main(
        [
            str(tmp_path / "catalog.zip"),
            "--project",
            "trs-80",
            "--database",
            "retrostore",
            "--bucket",
            "trs-80-retrostore-assets",
            "--output",
            str(output),
            "--apply",
            "--confirm-project",
            "trs-80",
            "--impersonate-service-account",
            "retrostore-migrator@trs-80.iam.gserviceaccount.com",
        ]
    )

    report = json.loads(output.read_text())
    assert result == 0
    assert report["applied"] is True
    assert report["documents_created"] == 5
    assert report["audit_created"] is True

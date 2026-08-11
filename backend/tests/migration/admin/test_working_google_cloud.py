from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import pytest

from retrostore.migration.admin.working_catalog import build_working_catalog_materialization
from retrostore.migration.admin.working_google_cloud import (
    FirestoreWorkingCatalogStore,
    WorkingCatalogConflictError,
)
from retrostore.migration.catalog_mirror import build_catalog_snapshot
from tests.migration.admin.test_working_catalog import _mirror


class FakeSnapshot:
    def __init__(self, path: tuple[str, ...], value: dict[str, Any] | None):
        self.id = path[-1]
        self.exists = value is not None
        self._value = deepcopy(value)

    def to_dict(self):
        return deepcopy(self._value)


class FakeDocument:
    def __init__(self, client, path):
        self.client = client
        self.path = path

    def get(self):
        return FakeSnapshot(self.path, self.client.documents.get(self.path))


class FakeCollection:
    def __init__(self, client, name):
        self.client = client
        self.name = name

    def document(self, document_id=None):
        document_id = document_id or f"audit-{self.client.next_audit}"
        if document_id.startswith("audit-"):
            self.client.next_audit += 1
        return FakeDocument(self.client, (self.name, document_id))

    def stream(self):
        return [
            FakeSnapshot(path, value)
            for path, value in self.client.documents.items()
            if len(path) == 2 and path[0] == self.name
        ]


class FakeBatch:
    def __init__(self, client):
        self.client = client
        self.creates = []

    def create(self, reference, value):
        self.creates.append((reference.path, deepcopy(value)))

    def commit(self):
        updated = deepcopy(self.client.documents)
        for path, value in self.creates:
            if path in updated:
                raise RuntimeError("create collision")
            updated[path] = value
        self.client.documents = updated


class FakeFirestore:
    def __init__(self):
        self.documents = {}
        self.next_audit = 1

    def collection(self, name):
        return FakeCollection(self, name)

    def batch(self):
        return FakeBatch(self)


def _materialization():
    mirror = _mirror()
    return build_working_catalog_materialization(mirror, build_catalog_snapshot(mirror))


def test_materialization_is_atomic_audited_and_idempotent() -> None:
    client = FakeFirestore()
    store = FirestoreWorkingCatalogStore(client)  # type: ignore[arg-type]
    materialization = _materialization()

    first = store.materialize(materialization, actor="migrator@example.test")
    second = store.materialize(materialization, actor="migrator@example.test")

    assert first.documents_created == 5
    assert first.documents_reused == 0
    assert first.audit_created is True
    assert second.documents_created == 0
    assert second.documents_reused == 5
    assert second.audit_created is False
    control = client.documents[("catalogWorkingControl", "current")]
    assert control["materializationId"] == materialization.id
    assert control["status"] == "READY"
    audits = [value for path, value in client.documents.items() if path[0] == "auditEvents"]
    assert len(audits) == 1
    assert audits[0]["eventType"] == "CATALOG_WORKING_SET_MATERIALIZED"


def test_materialization_refuses_any_preexisting_source_document_without_control() -> None:
    client = FakeFirestore()
    materialization = _materialization()
    app_id, app = next(iter(materialization.collections["apps"].items()))
    client.documents[("apps", app_id)] = dict(app)

    with pytest.raises(WorkingCatalogConflictError, match="already in use"):
        FirestoreWorkingCatalogStore(client).materialize(  # type: ignore[arg-type]
            materialization, actor="migrator@example.test"
        )


def test_existing_control_detects_missing_or_changed_materialized_documents() -> None:
    client = FakeFirestore()
    store = FirestoreWorkingCatalogStore(client)  # type: ignore[arg-type]
    materialization = _materialization()
    store.materialize(materialization, actor="migrator@example.test")
    app_id = next(iter(materialization.collections["apps"]))
    client.documents[("apps", app_id)]["name"] = "Changed"

    with pytest.raises(WorkingCatalogConflictError, match="document changed"):
        store.materialize(materialization, actor="migrator@example.test")


def test_existing_control_detects_missing_or_changed_audit_event() -> None:
    client = FakeFirestore()
    store = FirestoreWorkingCatalogStore(client)  # type: ignore[arg-type]
    materialization = _materialization()
    store.materialize(materialization, actor="migrator@example.test")
    audit_path = next(path for path in client.documents if path[0] == "auditEvents")
    client.documents[audit_path]["actorUid"] = "someone-else@example.test"

    with pytest.raises(WorkingCatalogConflictError, match="audit event changed"):
        store.materialize(materialization, actor="migrator@example.test")

    client.documents.pop(audit_path)
    with pytest.raises(WorkingCatalogConflictError, match="missing or duplicated"):
        store.materialize(materialization, actor="migrator@example.test")


def test_load_current_reconstructs_only_reconciled_source_documents() -> None:
    client = FakeFirestore()
    store = FirestoreWorkingCatalogStore(client)  # type: ignore[arg-type]
    expected = _materialization()
    store.materialize(expected, actor="migrator@example.test")
    client.documents[("apps", "new-staged-app")] = {
        "status": "STAGING",
        "name": "Not in the source baseline",
    }

    loaded = store.load_current(actor="migrator@example.test")

    assert loaded.id == expected.id
    assert loaded.manifest_sha256 == expected.manifest_sha256
    assert loaded.counts == expected.counts
    assert "new-staged-app" not in loaded.collections["apps"]


def test_load_current_rejects_another_materialized_source() -> None:
    client = FakeFirestore()
    store = FirestoreWorkingCatalogStore(client)  # type: ignore[arg-type]
    expected = _materialization()
    store.materialize(expected, actor="migrator@example.test")
    client.documents[("apps", "foreign-source")] = {
        "sourceKind": "APP_ENGINE_MIRROR",
        "sourceSnapshotId": "catalog-other",
    }

    with pytest.raises(WorkingCatalogConflictError, match="another source snapshot"):
        store.load_current(actor="migrator@example.test")


def test_load_staged_changes_excludes_source_and_retained_unreferenced_authors() -> None:
    client = FakeFirestore()
    store = FirestoreWorkingCatalogStore(client)  # type: ignore[arg-type]
    materialization = _materialization()
    store.materialize(materialization, actor="migrator@example.test")
    created = datetime(2026, 8, 10, tzinfo=UTC)
    app_id = "new-app"
    client.documents[("apps", app_id)] = {
        "schemaVersion": 1,
        "status": "STAGING",
        "authorId": "new-author",
    }
    client.documents[("authors", "new-author")] = {
        "schemaVersion": 1,
        "displayName": "New Author",
        "createdAt": created,
    }
    client.documents[("authors", "retained-author")] = {
        "schemaVersion": 1,
        "displayName": "Retained",
        "createdAt": created,
    }
    client.documents[("media", "new-media")] = {
        "schemaVersion": 1,
        "appId": app_id,
    }

    changes = store.load_staged_changes()

    assert set(changes["apps"]) == {app_id}
    assert set(changes["authors"]) == {"new-author"}
    assert set(changes["media"]) == {"new-media"}
    assert changes["screenshots"] == {}


def test_load_staged_changes_includes_published_app_drafts() -> None:
    client = FakeFirestore()
    store = FirestoreWorkingCatalogStore(client)  # type: ignore[arg-type]
    materialization = _materialization()
    store.materialize(materialization, actor="migrator@example.test")
    app_id = next(iter(materialization.collections["apps"]))
    client.documents[("appDrafts", app_id)] = {
        "schemaVersion": 1,
        "status": "DRAFT",
        "authorId": next(iter(materialization.collections["authors"])),
    }

    changes = store.load_staged_changes()

    assert set(changes["apps"]) == {app_id}


def test_load_staged_changes_merges_separate_draft_asset_collections() -> None:
    client = FakeFirestore()
    store = FirestoreWorkingCatalogStore(client)  # type: ignore[arg-type]
    materialization = _materialization()
    store.materialize(materialization, actor="migrator@example.test")
    app_id = next(iter(materialization.collections["apps"]))
    client.documents[("appDrafts", app_id)] = {
        "schemaVersion": 1,
        "status": "DRAFT",
        "authorId": next(iter(materialization.collections["authors"])),
    }
    client.documents[("appDraftMedia", "draft-media")] = {
        "schemaVersion": 1,
        "appId": app_id,
    }
    client.documents[("appDraftScreenshots", "draft-shot")] = {
        "schemaVersion": 1,
        "appId": app_id,
    }

    changes = store.load_staged_changes()

    assert set(changes["media"]) == {"draft-media"}
    assert set(changes["screenshots"]) == {"draft-shot"}

import pytest

import retrostore.admin.drafts as drafts
from retrostore.admin.auth import AdminIdentity
from retrostore.admin.staging import (
    StagedAppDraft,
    StagingAuthorizationError,
    StagingConflictError,
)
from tests.admin.test_staging import (
    FakeCollection,
    FakeFirestore,
    FakeSnapshot,
    _app_document,
)

ADMIN = AdminIdentity("admin-1", "admin@example.test", "administrator")
PUBLISHER = AdminIdentity("publisher-1", "publisher@example.test", "publisher")
APP_ID = "0FA9D58E-9B99-11E7-B002-5B6133CA5F0C"


def _source_document():
    return {
        **_app_document(publisher_uid="", name="Published Game"),
        "schemaVersion": 1,
        "status": "PUBLISHED",
        "sourceSnapshotId": "catalog-source",
        "sourceFingerprint": "a" * 64,
        "sourceAuthorId": "42",
        "publisherEmail": "legacy@example.test",
        "firstPublishedAtMs": 1_500_000_000_000,
        "updatedAtMs": 1_600_000_000_000,
        "mediaSlots": {
            "disks": ["100", None, None, None],
            "cassette": None,
            "command": None,
            "basic": None,
        },
        "screenshotIds": ["screenshot-source"],
        "revision": 1,
    }


def _draft_document(*, revision=1, owner="admin-1"):
    return {
        **_source_document(),
        "status": "DRAFT",
        "publisherUid": owner,
        "publisherEmail": "legacy@example.test",
        "revision": revision,
        "baseSnapshotId": "catalog-source",
        "baseSourceFingerprint": "a" * 64,
        "baseAuthorId": "author-1",
        "baseAuthorName": "Jane Doe",
        "baseSourceAuthorId": "42",
    }


def _client(*, draft=None):
    client = FakeFirestore(apps=(FakeSnapshot(APP_ID, _source_document()),))
    client.collections["appDrafts"] = FakeCollection(
        {} if draft is None else {APP_ID: _fake_document(APP_ID, draft)}
    )
    return client


def _fake_document(document_id, value):
    from tests.admin.test_staging import FakeDocument

    snapshot = FakeSnapshot(document_id, value)
    return FakeDocument(document_id, snapshot)


def _draft(**overrides):
    values = {
        "name": "Edited Game",
        "version": "2.0",
        "description": "Edited metadata.",
        "release_year": 1984,
        "model": "MODEL_III",
        "category": "OTHER",
        "author_name": "New Author",
    }
    values.update(overrides)
    return StagedAppDraft(**values)


def test_create_copies_published_metadata_into_separate_audited_draft(
    monkeypatch,
) -> None:
    monkeypatch.setattr(drafts.firestore, "transactional", lambda function: function)
    client = _client()
    store = drafts.FirestorePublishedAppDrafts(client)

    result = store.create(identity=ADMIN, app_id=APP_ID)

    assert result.id == APP_ID
    assert result.status == "DRAFT"
    assert result.publisher_uid == ADMIN.uid
    assert result.disk_media_ids[0] == "100"
    assert result.screenshot_ids == ("screenshot-source",)
    creates = client.transaction_value.creates
    assert creates[0][0] == APP_ID
    assert creates[0][1]["baseSnapshotId"] == "catalog-source"
    assert creates[0][1]["baseSourceFingerprint"] == "a" * 64
    assert creates[0][1]["baseAuthorId"] == "author-1"
    assert creates[0][1]["baseSourceAuthorId"] == "42"
    assert creates[0][1]["publisherEmail"] == "legacy@example.test"
    assert creates[1][1]["eventType"] == "PUBLISHED_APP_DRAFT_CREATED"
    assert client.transaction_value.sets == []


def test_publisher_cannot_create_a_published_baseline_draft(monkeypatch) -> None:
    monkeypatch.setattr(drafts.firestore, "transactional", lambda function: function)
    client = _client()

    with pytest.raises(StagingAuthorizationError, match="administrators"):
        drafts.FirestorePublishedAppDrafts(client).create(
            identity=PUBLISHER, app_id=APP_ID
        )

    assert client.transaction_value.creates == []


def test_update_is_optimistic_and_preserves_inherited_assets(monkeypatch) -> None:
    monkeypatch.setattr(drafts.firestore, "transactional", lambda function: function)
    client = _client(draft=_draft_document(revision=3))
    store = drafts.FirestorePublishedAppDrafts(client)

    result = store.update(
        identity=ADMIN,
        app_id=APP_ID,
        expected_revision=3,
        draft=_draft(),
    )

    assert result.name == "Edited Game"
    assert result.status == "DRAFT"
    assert result.revision == 4
    assert result.disk_media_ids[0] == "100"
    assert result.screenshot_ids == ("screenshot-source",)
    assert client.transaction_value.sets[0][1]["sourceAuthorId"] is None
    assert client.transaction_value.creates[0][1]["eventType"] == (
        "PUBLISHED_APP_DRAFT_UPDATED"
    )

    stale_client = _client(draft=_draft_document(revision=3))
    with pytest.raises(StagingConflictError, match="concurrently"):
        drafts.FirestorePublishedAppDrafts(stale_client).update(
            identity=ADMIN,
            app_id=APP_ID,
            expected_revision=2,
            draft=_draft(),
        )


def test_discard_deletes_only_the_overlay_and_audits(monkeypatch) -> None:
    monkeypatch.setattr(drafts.firestore, "transactional", lambda function: function)
    client = _client(draft=_draft_document(revision=2))
    store = drafts.FirestorePublishedAppDrafts(client)

    store.discard(identity=ADMIN, app_id=APP_ID, expected_revision=2)

    assert client.transaction_value.deletes == [APP_ID]
    assert client.transaction_value.creates[0][1]["eventType"] == (
        "PUBLISHED_APP_DRAFT_DISCARDED"
    )
    assert client.collections["apps"].document(APP_ID).snapshot.exists is True


def test_update_can_restore_the_published_author_identity(monkeypatch) -> None:
    monkeypatch.setattr(drafts.firestore, "transactional", lambda function: function)
    client = _client(
        draft={
            **_draft_document(revision=3),
            "authorId": "draft-changed",
            "authorName": "Changed Author",
            "sourceAuthorId": None,
        }
    )

    result = drafts.FirestorePublishedAppDrafts(client).update(
        identity=ADMIN,
        app_id=APP_ID,
        expected_revision=3,
        draft=_draft(author_name="Jane Doe"),
    )

    assert result.author_id == "author-1"
    update = client.transaction_value.sets[0][1]
    assert update["authorId"] == "author-1"
    assert update["sourceAuthorId"] == "42"

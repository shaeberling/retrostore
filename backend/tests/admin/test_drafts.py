import hashlib

import pytest

import retrostore.admin.drafts as drafts
from retrostore.admin.assets import validate_media_upload, validate_screenshot_upload
from retrostore.admin.auth import AdminIdentity
from retrostore.admin.staging import (
    StagedAppDraft,
    StagingAuthorizationError,
    StagingConflictError,
)
from tests.admin.test_staging import (
    FakeCollection,
    FakeFirestore,
    FakeObjectStore,
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
    client.collections["appDraftMedia"] = FakeCollection()
    client.collections["appDraftScreenshots"] = FakeCollection()
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


def test_draft_detail_combines_inherited_and_copy_on_write_assets() -> None:
    client = _client(draft=_draft_document())
    media_digest = "b" * 64
    screenshot_digest = "c" * 64
    client.collections["media"] = FakeCollection(
        {
            "100": _fake_document(
                "100",
                {
                    "appId": APP_ID,
                    "mediaType": "DISK",
                    "slot": "disk-1",
                    "filename": "published.dmk",
                    "description": "",
                    "contentType": "application/octet-stream",
                    "objectPath": f"media/{APP_ID}/100/{media_digest}",
                    "size": 4,
                    "sha256": media_digest,
                },
            )
        }
    )
    client.collections["screenshots"] = FakeCollection(
        {
            "screenshot-source": _fake_document(
                "screenshot-source",
                {
                    "appId": APP_ID,
                    "filename": "published.png",
                    "contentType": "image/png",
                    "objectPath": (
                        f"screenshots/{APP_ID}/screenshot-source/"
                        f"{screenshot_digest}.png"
                    ),
                    "size": 8,
                    "sha256": screenshot_digest,
                },
            )
        }
    )

    detail = drafts.FirestorePublishedAppDrafts(client).get_detail(ADMIN, APP_ID)

    assert detail is not None
    assert detail.app.status == "DRAFT"
    assert detail.media[0].filename == "published.dmk"
    assert detail.screenshots[0].filename == "published.png"


def test_draft_media_replacement_never_deletes_inherited_media(
    monkeypatch,
) -> None:
    monkeypatch.setattr(drafts.firestore, "transactional", lambda function: function)
    monkeypatch.setattr(drafts, "new_staged_asset_id", lambda: "new-media")
    client = _client(draft=_draft_document(revision=3))
    objects = FakeObjectStore()
    store = drafts.FirestorePublishedAppDrafts(client, objects)
    upload = validate_media_upload(
        filename="replacement.dmk", body=b"replacement", description="New"
    )

    result = store.upload_media(
        identity=ADMIN,
        app_id=APP_ID,
        expected_revision=3,
        slot="disk-1",
        upload=upload,
    )

    assert result.disk_media_ids[0] == "new-media"
    assert result.revision == 4
    assert client.transaction_value.deletes == []
    created = client.transaction_value.creates[0][1]
    assert created["appId"] == APP_ID
    assert created["slot"] == "disk-1"
    assert objects.deletes == []


def test_draft_can_remove_an_inherited_asset_without_deleting_its_object(
    monkeypatch,
) -> None:
    monkeypatch.setattr(drafts.firestore, "transactional", lambda function: function)
    client = _client(draft=_draft_document(revision=2))
    objects = FakeObjectStore()

    result = drafts.FirestorePublishedAppDrafts(client, objects).delete_media(
        identity=ADMIN,
        app_id=APP_ID,
        media_id="100",
        expected_revision=2,
    )

    assert result.disk_media_ids[0] is None
    assert client.transaction_value.deletes == []
    assert objects.deletes == []
    assert client.transaction_value.creates[0][1]["inherited"] is True


def test_draft_removal_deletes_only_a_copy_on_write_media_object(monkeypatch) -> None:
    monkeypatch.setattr(drafts.firestore, "transactional", lambda function: function)
    body = b"draft media"
    digest = hashlib.sha256(body).hexdigest()
    path = f"media/{APP_ID}/draft-media/{digest}"
    document = {
        "schemaVersion": 1,
        "appId": APP_ID,
        "mediaType": "DISK",
        "slot": "disk-1",
        "filename": "draft.dmk",
        "description": "",
        "contentType": "application/octet-stream",
        "objectPath": path,
        "size": len(body),
        "sha256": digest,
    }
    client = _client(
        draft={
            **_draft_document(revision=2),
            "mediaSlots": {
                "disks": ["draft-media", None, None, None],
                "cassette": None,
                "command": None,
                "basic": None,
            },
        }
    )
    client.collections["appDraftMedia"] = FakeCollection(
        {"draft-media": _fake_document("draft-media", document)}
    )
    objects = FakeObjectStore({path: body})

    drafts.FirestorePublishedAppDrafts(client, objects).delete_media(
        identity=ADMIN,
        app_id=APP_ID,
        media_id="draft-media",
        expected_revision=2,
    )

    assert client.transaction_value.deletes == ["draft-media"]
    assert objects.deletes == [path]


def test_draft_screenshot_upload_uses_a_separate_collection(monkeypatch) -> None:
    monkeypatch.setattr(drafts.firestore, "transactional", lambda function: function)
    monkeypatch.setattr(drafts, "new_staged_asset_id", lambda: "new-shot")
    client = _client(draft=_draft_document(revision=4))
    objects = FakeObjectStore()
    upload = validate_screenshot_upload(
        filename="new.png", body=b"\x89PNG\r\n\x1a\nnew"
    )

    result = drafts.FirestorePublishedAppDrafts(client, objects).upload_screenshot(
        identity=ADMIN,
        app_id=APP_ID,
        expected_revision=4,
        upload=upload,
    )

    assert result.screenshot_ids == ("screenshot-source", "new-shot")
    assert client.transaction_value.creates[0][0] == "new-shot"
    assert client.transaction_value.creates[0][1]["position"] == 1
    assert any(path.startswith(f"screenshots/{APP_ID}/new-shot/") for path in objects.objects)


def test_draft_screenshot_read_verifies_bytes_from_source_or_overlay() -> None:
    body = b"\x89PNG\r\n\x1a\nsource"
    digest = hashlib.sha256(body).hexdigest()
    path = f"screenshots/{APP_ID}/screenshot-source/{digest}.png"
    client = _client(draft=_draft_document())
    client.collections["screenshots"] = FakeCollection(
        {
            "screenshot-source": _fake_document(
                "screenshot-source",
                {
                    "appId": APP_ID,
                    "filename": "source.png",
                    "contentType": "image/png",
                    "objectPath": path,
                    "size": len(body),
                    "sha256": digest,
                },
            )
        }
    )

    result = drafts.FirestorePublishedAppDrafts(
        client, FakeObjectStore({path: body})
    ).read_screenshot(ADMIN, APP_ID, "screenshot-source")

    assert result is not None
    assert result[1] == body


def test_discard_cascades_only_copy_on_write_assets(monkeypatch) -> None:
    monkeypatch.setattr(drafts.firestore, "transactional", lambda function: function)
    media_path = f"media/{APP_ID}/draft-media/{'d' * 64}"
    screenshot_path = f"screenshots/{APP_ID}/draft-shot/{'e' * 64}.png"
    client = _client(draft=_draft_document(revision=5))
    client.collections["appDraftMedia"] = FakeCollection(
        {
            "draft-media": _fake_document(
                "draft-media", {"appId": APP_ID, "objectPath": media_path}
            )
        }
    )
    client.collections["appDraftScreenshots"] = FakeCollection(
        {
            "draft-shot": _fake_document(
                "draft-shot", {"appId": APP_ID, "objectPath": screenshot_path}
            )
        }
    )
    objects = FakeObjectStore({media_path: b"media", screenshot_path: b"shot"})

    drafts.FirestorePublishedAppDrafts(client, objects).discard(
        identity=ADMIN, app_id=APP_ID, expected_revision=5
    )

    assert set(client.transaction_value.deletes) == {
        "draft-media",
        "draft-shot",
        APP_ID,
    }
    assert objects.deletes == [media_path, screenshot_path]
    assert client.collections["apps"].document(APP_ID).snapshot.exists is True

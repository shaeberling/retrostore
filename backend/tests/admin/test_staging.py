import uuid

import pytest

import retrostore.admin.staging as staging
from retrostore.admin.assets import validate_media_upload, validate_screenshot_upload
from retrostore.admin.auth import AdminIdentity
from retrostore.admin.rpk import RpkMedia, ValidatedRpk

ADMIN = AdminIdentity("admin-1", "admin@example.test", "administrator")
PUBLISHER = AdminIdentity("publisher-1", "publisher@example.test", "publisher")


def _draft(**overrides):
    values = {
        "name": "Space Game",
        "version": "1.0",
        "description": "A staged application.",
        "release_year": 1982,
        "model": "MODEL_I",
        "category": "GAME",
        "author_name": "Jane Doe",
    }
    values.update(overrides)
    return staging.StagedAppDraft(**values)


def _form(**overrides):
    values = {
        "request_id": "11111111-1111-4111-8111-111111111111",
        "name": " Space Game ",
        "version": " 1.0 ",
        "description": " A staged application. ",
        "release_year": "1982",
        "model": "MODEL_I",
        "category": "GAME",
        "author_name": " Jane   Doe ",
    }
    values.update(overrides)
    return values


def _rpk() -> ValidatedRpk:
    return ValidatedRpk(
        filename="game.rpk",
        package_sha256="a" * 64,
        package_size=1234,
        app_id="8c028afe-96b3-11e7-a68b-5b6133ca5f0c",
        name="Imported Game",
        version="1.0",
        description="Imported as one complete package.",
        release_year=1982,
        model="MODEL_III",
        category="GAME",
        author_name="Jane Doe",
        claimed_publisher_name="Untrusted Publisher",
        claimed_publisher_email="untrusted@example.test",
        media=(
            RpkMedia(
                "disk-1",
                validate_media_upload(
                    filename="disk_0.dmk", body=b"disk", description=""
                ),
            ),
            RpkMedia(
                "command",
                validate_media_upload(
                    filename="command.cmd", body=b"command", description=""
                ),
            ),
        ),
        screenshots=(
            validate_screenshot_upload(
                filename="screenshot_1.png",
                body=b"\x89PNG\r\n\x1a\ncontent",
            ),
        ),
    )


def test_staged_app_form_normalizes_valid_input() -> None:
    result = staging.validate_staged_app_form(_form())

    assert result.errors == {}
    assert result.draft == _draft()
    assert result.values["request_id"] == "11111111-1111-4111-8111-111111111111"


def test_staged_app_form_rejects_invalid_fields_and_preserves_values() -> None:
    result = staging.validate_staged_app_form(
        _form(
            request_id="bad",
            name=" ",
            version="v" * 65,
            description="",
            release_year="yesterday",
            model="MODEL_II",
            category="UNKNOWN",
            author_name="",
        )
    )

    assert result.draft is None
    assert set(result.errors) == {
        "request_id",
        "name",
        "version",
        "description",
        "release_year",
        "model",
        "category",
        "author_name",
    }
    assert result.values["version"] == "v" * 65


class FakeSnapshot:
    def __init__(self, document_id, value=None):
        self.id = document_id
        self.value = value
        self.exists = value is not None

    def to_dict(self):
        return self.value


class FakeDocument:
    def __init__(self, document_id, snapshot=None):
        self.id = document_id
        self.snapshot = snapshot or FakeSnapshot(document_id)

    def get(self, *, transaction=None):
        return self.snapshot


class FakeCollection:
    def __init__(self, documents=None):
        self.documents = documents or {}

    def document(self, document_id=None):
        document_id = document_id or "audit-1"
        return self.documents.setdefault(document_id, FakeDocument(document_id))

    def stream(self):
        return (
            document.snapshot
            for document in self.documents.values()
            if document.snapshot.exists
        )


class FakeTransaction:
    def __init__(self):
        self.creates = []
        self.sets = []
        self.deletes = []

    def create(self, reference, value):
        self.creates.append((reference.id, value))

    def set(self, reference, value, *, merge=False):
        self.sets.append((reference.id, value, merge))

    def delete(self, reference):
        self.deletes.append(reference.id)


class FakeFirestore:
    def __init__(self, *, apps=(), authors=(), media=(), screenshots=()):
        self.collection_names = []
        self.collections = {
            "apps": FakeCollection(
                {
                    snapshot.id: FakeDocument(snapshot.id, snapshot)
                    for snapshot in apps
                }
            ),
            "authors": FakeCollection(
                {
                    snapshot.id: FakeDocument(snapshot.id, snapshot)
                    for snapshot in authors
                }
            ),
            "media": FakeCollection(
                {
                    snapshot.id: FakeDocument(snapshot.id, snapshot)
                    for snapshot in media
                }
            ),
            "screenshots": FakeCollection(
                {
                    snapshot.id: FakeDocument(snapshot.id, snapshot)
                    for snapshot in screenshots
                }
            ),
            "auditEvents": FakeCollection(),
        }
        self.transaction_value = FakeTransaction()

    def collection(self, name):
        self.collection_names.append(name)
        return self.collections[name]

    def transaction(self):
        return self.transaction_value


class FakeObjectStore:
    def __init__(self, objects=None):
        self.objects = dict(objects or {})
        self.puts = []
        self.deletes = []

    def put_verified(self, *, path, body, sha256, content_type):
        self.puts.append((path, body, sha256, content_type))
        if path in self.objects:
            return False
        self.objects[path] = bytes(body)
        return True

    def read(self, path):
        return self.objects[path]

    def delete(self, path):
        self.deletes.append(path)
        self.objects.pop(path, None)


def _app_document(*, publisher_uid, name):
    return {
        "name": name,
        "version": "1.0",
        "description": "Staged",
        "releaseYear": 1982,
        "model": "MODEL_I",
        "categories": ["GAME"],
        "authorId": "author-1",
        "authorName": "Jane Doe",
        "publisherUid": publisher_uid,
        "publisherEmail": f"{publisher_uid}@example.test",
    }


def test_publishers_list_only_owned_staged_apps() -> None:
    client = FakeFirestore(
        apps=(
            FakeSnapshot("owned", _app_document(publisher_uid="publisher-1", name="Owned")),
            FakeSnapshot("other", _app_document(publisher_uid="publisher-2", name="Other")),
        )
    )
    catalog = staging.FirestoreAdminStagingCatalog(client)

    publisher_apps = catalog.list_apps(PUBLISHER)
    admin_apps = catalog.list_apps(ADMIN)

    assert [app.id for app in publisher_apps] == ["owned"]
    assert [app.id for app in admin_apps] == ["other", "owned"]


def test_staged_creation_writes_author_app_and_audit_atomically(monkeypatch) -> None:
    monkeypatch.setattr(staging.firestore, "transactional", lambda function: function)
    client = FakeFirestore()
    catalog = staging.FirestoreAdminStagingCatalog(client)
    request_id = "22222222-2222-4222-8222-222222222222"

    app = catalog.create_app(identity=PUBLISHER, request_id=request_id, draft=_draft())

    assert app.id == request_id
    assert app.publisher_uid == "publisher-1"
    assert client.collection_names.count("apps") == 1
    assert "catalogSnapshots" not in client.collection_names
    creates = client.transaction_value.creates
    assert len(creates) == 3
    author_id, author = creates[0]
    app_id, document = creates[1]
    audit_id, audit = creates[2]
    assert author_id.startswith("new-")
    assert author["displayName"] == "Jane Doe"
    assert app_id == request_id
    assert document["status"] == "STAGING"
    assert document["mediaSlots"]["disks"] == [None, None, None, None]
    assert document["publisherUid"] == "publisher-1"
    assert len(document["creationDigest"]) == 64
    assert audit_id == "audit-1"
    assert audit["eventType"] == "STAGED_APP_CREATED"
    assert audit["actorUid"] == "publisher-1"


def test_rpk_import_uploads_immutable_assets_and_commits_metadata_atomically(
    monkeypatch,
) -> None:
    monkeypatch.setattr(staging.firestore, "transactional", lambda function: function)
    asset_ids = iter(
        (
            "11111111-1111-4111-8111-111111111111",
            "22222222-2222-4222-8222-222222222222",
            "33333333-3333-4333-8333-333333333333",
        )
    )
    monkeypatch.setattr(staging, "new_staged_asset_id", lambda: next(asset_ids))
    client = FakeFirestore()
    store = FakeObjectStore()
    catalog = staging.FirestoreAdminStagingCatalog(client, store)

    app = catalog.import_rpk(identity=PUBLISHER, package=_rpk())

    assert app.id == "8c028afe-96b3-11e7-a68b-5b6133ca5f0c"
    assert app.publisher_uid == PUBLISHER.uid
    assert app.disk_media_ids[0] == "11111111-1111-4111-8111-111111111111"
    assert app.command_media_id == "22222222-2222-4222-8222-222222222222"
    assert app.screenshot_ids == ("33333333-3333-4333-8333-333333333333",)
    assert len(store.puts) == 3
    assert len(store.objects) == 3

    creations = {document_id: value for document_id, value in client.transaction_value.creates}
    app_document = creations[app.id]
    assert app_document["creationSource"] == "RPK"
    assert app_document["sourcePackageSha256"] == "a" * 64
    assert app_document["mediaSlots"]["disks"][0] == app.disk_media_ids[0]
    assert app_document["mediaSlots"]["command"] == app.command_media_id
    assert app_document["screenshotIds"] == list(app.screenshot_ids)
    assert creations[app.disk_media_ids[0]]["slot"] == "disk-1"
    assert creations[app.command_media_id]["slot"] == "command"
    assert creations[app.screenshot_ids[0]]["position"] == 0
    audit = creations["audit-1"]
    assert audit["eventType"] == "STAGED_RPK_IMPORTED"
    assert audit["actorUid"] == PUBLISHER.uid
    assert audit["mediaCount"] == 2
    assert audit["screenshotCount"] == 1
    assert "untrusted@example.test" not in repr(creations)


def test_rpk_import_refuses_existing_app_id_and_removes_new_objects(monkeypatch) -> None:
    monkeypatch.setattr(staging.firestore, "transactional", lambda function: function)
    asset_ids = iter(
        (
            "11111111-1111-4111-8111-111111111111",
            "22222222-2222-4222-8222-222222222222",
            "33333333-3333-4333-8333-333333333333",
        )
    )
    monkeypatch.setattr(staging, "new_staged_asset_id", lambda: next(asset_ids))
    client = FakeFirestore(
        apps=(FakeSnapshot("8c028afe-96b3-11e7-a68b-5b6133ca5f0c", {}),)
    )
    store = FakeObjectStore()
    catalog = staging.FirestoreAdminStagingCatalog(client, store)

    with pytest.raises(staging.StagingConflictError, match="already uses"):
        catalog.import_rpk(identity=PUBLISHER, package=_rpk())

    assert store.objects == {}
    assert len(store.deletes) == 3
    assert client.transaction_value.creates == []


def test_staged_creation_is_idempotent_for_same_request_and_content(monkeypatch) -> None:
    monkeypatch.setattr(staging.firestore, "transactional", lambda function: function)
    request_id = "33333333-3333-4333-8333-333333333333"
    app = staging.StagedApp(
        id=request_id,
        name="Space Game",
        version="1.0",
        description="A staged application.",
        release_year=1982,
        model="MODEL_I",
        category="GAME",
        author_id=staging._author_id("Jane Doe"),
        author_name="Jane Doe",
        publisher_uid="publisher-1",
        publisher_email="publisher@example.test",
        revision=1,
    )
    existing = staging._app_document(app, request_id=request_id)
    client = FakeFirestore(apps=(FakeSnapshot(request_id, existing),))
    catalog = staging.FirestoreAdminStagingCatalog(client)

    result = catalog.create_app(
        identity=PUBLISHER,
        request_id=request_id,
        draft=_draft(),
    )

    assert result.id == request_id
    assert client.transaction_value.creates == []


def test_staged_creation_rejects_reused_request_id(monkeypatch) -> None:
    monkeypatch.setattr(staging.firestore, "transactional", lambda function: function)
    request_id = "44444444-4444-4444-8444-444444444444"
    client = FakeFirestore(
        apps=(FakeSnapshot(request_id, {"creationRequestId": request_id}),)
    )
    catalog = staging.FirestoreAdminStagingCatalog(client)

    with pytest.raises(staging.StagingConflictError, match="already in use"):
        catalog.create_app(
            identity=PUBLISHER,
            request_id=request_id,
            draft=_draft(),
        )

    assert client.transaction_value.creates == []


def test_staged_update_checks_ownership_revision_and_audits_atomically(
    monkeypatch,
) -> None:
    monkeypatch.setattr(staging.firestore, "transactional", lambda function: function)
    app_id = "55555555-5555-4555-8555-555555555555"
    client = FakeFirestore(
        apps=(
            FakeSnapshot(
                app_id,
                {
                    **_app_document(publisher_uid="publisher-1", name="Old Name"),
                    "revision": 3,
                },
            ),
        )
    )
    catalog = staging.FirestoreAdminStagingCatalog(client)

    updated = catalog.update_app(
        identity=PUBLISHER,
        app_id=app_id,
        expected_revision=3,
        draft=_draft(name="New Name", author_name="New Author"),
    )

    assert updated.name == "New Name"
    assert updated.publisher_uid == "publisher-1"
    assert updated.revision == 4
    assert len(client.transaction_value.sets) == 1
    update_id, document, merge = client.transaction_value.sets[0]
    assert update_id == app_id
    assert document["name"] == "New Name"
    assert document["revision"] == 4
    assert merge is True
    assert len(client.transaction_value.creates) == 2
    assert client.transaction_value.creates[1][1]["eventType"] == "STAGED_APP_UPDATED"


def test_staged_update_rejects_non_owner_and_stale_revision(monkeypatch) -> None:
    monkeypatch.setattr(staging.firestore, "transactional", lambda function: function)
    app_id = "66666666-6666-4666-8666-666666666666"
    snapshot = FakeSnapshot(
        app_id,
        {
            **_app_document(publisher_uid="publisher-2", name="Other App"),
            "revision": 2,
        },
    )
    client = FakeFirestore(apps=(snapshot,))
    catalog = staging.FirestoreAdminStagingCatalog(client)

    with pytest.raises(staging.StagingAuthorizationError):
        catalog.update_app(
            identity=PUBLISHER,
            app_id=app_id,
            expected_revision=2,
            draft=_draft(),
        )
    with pytest.raises(staging.StagingConflictError, match="concurrently"):
        catalog.update_app(
            identity=ADMIN,
            app_id=app_id,
            expected_revision=1,
            draft=_draft(),
        )

    assert client.transaction_value.sets == []
    assert client.transaction_value.creates == []


def test_staged_delete_requires_current_revision_and_keeps_author(monkeypatch) -> None:
    monkeypatch.setattr(staging.firestore, "transactional", lambda function: function)
    app_id = "77777777-7777-4777-8777-777777777777"
    client = FakeFirestore(
        apps=(
            FakeSnapshot(
                app_id,
                {
                    **_app_document(publisher_uid="publisher-1", name="Delete Me"),
                    "revision": 5,
                },
            ),
        ),
        authors=(FakeSnapshot("author-1", {"normalizedName": "jane doe"}),),
    )
    catalog = staging.FirestoreAdminStagingCatalog(client)

    catalog.delete_app(
        identity=PUBLISHER,
        app_id=app_id,
        expected_revision=5,
    )

    assert client.transaction_value.deletes == [app_id]
    assert len(client.transaction_value.creates) == 1
    assert client.transaction_value.creates[0][1]["eventType"] == "STAGED_APP_DELETED"
    assert "authors" not in client.collection_names


def test_generated_request_ids_are_canonical_uuid4() -> None:
    value = staging.new_staged_app_request_id()

    assert str(uuid.UUID(value)) == value
    assert uuid.UUID(value).version == 4


def test_staged_media_upload_replaces_slot_atomically_and_cleans_old_object(
    monkeypatch,
) -> None:
    monkeypatch.setattr(staging.firestore, "transactional", lambda function: function)
    app_id = "88888888-8888-4888-8888-888888888888"
    old_id = "99999999-9999-4999-8999-999999999999"
    new_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    monkeypatch.setattr(staging, "new_staged_asset_id", lambda: new_id)
    old_sha = "0" * 64
    old_path = f"media/{app_id}/{old_id}/{old_sha}"
    app_document = {
        **_app_document(publisher_uid="publisher-1", name="Media App"),
        "revision": 4,
        "mediaSlots": {
            "disks": [old_id, None, None, None],
            "cassette": None,
            "command": None,
            "basic": None,
        },
    }
    old_media = {
        "appId": app_id,
        "mediaType": "DISK",
        "slot": "disk-1",
        "filename": "old.dmk",
        "description": "",
        "contentType": "application/octet-stream",
        "objectPath": old_path,
        "size": 3,
        "sha256": old_sha,
    }
    store = FakeObjectStore({old_path: b"old"})
    client = FakeFirestore(
        apps=(FakeSnapshot(app_id, app_document),),
        media=(FakeSnapshot(old_id, old_media),),
    )
    catalog = staging.FirestoreAdminStagingCatalog(client, store)
    upload = validate_media_upload(
        filename="disk.dmk", body=b"new disk", description="Boot disk"
    )

    updated = catalog.upload_media(
        identity=PUBLISHER,
        app_id=app_id,
        expected_revision=4,
        slot="disk-1",
        upload=upload,
    )

    assert updated.disk_media_ids == (new_id, None, None, None)
    assert updated.revision == 5
    new_path = f"media/{app_id}/{new_id}/{upload.sha256}"
    assert store.puts[0] == (
        new_path,
        b"new disk",
        upload.sha256,
        "application/octet-stream",
    )
    assert store.deletes == [old_path]
    assert client.transaction_value.deletes == [old_id]
    assert client.transaction_value.creates[0][0] == new_id
    assert client.transaction_value.creates[0][1]["slot"] == "disk-1"
    assert client.transaction_value.creates[1][1]["eventType"] == (
        "STAGED_MEDIA_UPLOADED"
    )
    assert client.transaction_value.sets[0][1]["mediaSlots"]["disks"][0] == new_id


def test_staged_screenshot_upload_and_order_move_are_revision_guarded(
    monkeypatch,
) -> None:
    monkeypatch.setattr(staging.firestore, "transactional", lambda function: function)
    app_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    first_id = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    second_id = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
    monkeypatch.setattr(staging, "new_staged_asset_id", lambda: second_id)
    app_document = {
        **_app_document(publisher_uid="publisher-1", name="Screenshot App"),
        "revision": 2,
        "screenshotIds": [first_id],
    }
    store = FakeObjectStore()
    client = FakeFirestore(apps=(FakeSnapshot(app_id, app_document),))
    catalog = staging.FirestoreAdminStagingCatalog(client, store)
    upload = validate_screenshot_upload(
        filename="screen.png", body=b"\x89PNG\r\n\x1a\ncontent"
    )

    updated = catalog.upload_screenshot(
        identity=PUBLISHER,
        app_id=app_id,
        expected_revision=2,
        upload=upload,
    )

    assert updated.screenshot_ids == (first_id, second_id)
    assert updated.revision == 3
    assert client.transaction_value.creates[0][0] == second_id
    assert client.transaction_value.creates[1][1]["eventType"] == (
        "STAGED_SCREENSHOT_UPLOADED"
    )
    assert client.transaction_value.sets[0][1]["screenshotIds"] == [
        first_id,
        second_id,
    ]

    first_sha = "1" * 64
    second_sha = "2" * 64
    move_app = {**app_document, "revision": 3, "screenshotIds": [first_id, second_id]}
    screenshots = (
        FakeSnapshot(
            first_id,
            {
                "appId": app_id,
                "filename": "first.png",
                "contentType": "image/png",
                "objectPath": f"screenshots/{app_id}/{first_id}/{first_sha}.png",
                "size": 10,
                "sha256": first_sha,
            },
        ),
        FakeSnapshot(
            second_id,
            {
                "appId": app_id,
                "filename": "second.png",
                "contentType": "image/png",
                "objectPath": f"screenshots/{app_id}/{second_id}/{second_sha}.png",
                "size": 10,
                "sha256": second_sha,
            },
        ),
    )
    move_client = FakeFirestore(
        apps=(FakeSnapshot(app_id, move_app),), screenshots=screenshots
    )
    move_catalog = staging.FirestoreAdminStagingCatalog(move_client, store)

    moved = move_catalog.move_screenshot(
        identity=PUBLISHER,
        app_id=app_id,
        screenshot_id=first_id,
        expected_revision=3,
        direction="down",
    )

    assert moved.screenshot_ids == (second_id, first_id)
    assert moved.revision == 4
    assert move_client.transaction_value.sets[0][1]["screenshotIds"] == [
        second_id,
        first_id,
    ]
    assert move_client.transaction_value.creates[0][1]["eventType"] == (
        "STAGED_SCREENSHOT_MOVED"
    )


def test_staged_app_detail_and_delete_cascade_verify_asset_relationships(
    monkeypatch,
) -> None:
    monkeypatch.setattr(staging.firestore, "transactional", lambda function: function)
    app_id = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
    media_id = "ffffffff-ffff-4fff-8fff-ffffffffffff"
    screenshot_id = "12121212-1212-4212-8212-121212121212"
    media_sha = "3" * 64
    screenshot_sha = "4" * 64
    media_path = f"media/{app_id}/{media_id}/{media_sha}"
    screenshot_path = (
        f"screenshots/{app_id}/{screenshot_id}/{screenshot_sha}.png"
    )
    app_document = {
        **_app_document(publisher_uid="publisher-1", name="Cascade App"),
        "revision": 6,
        "mediaSlots": {
            "disks": [None, None, None, None],
            "cassette": None,
            "command": media_id,
            "basic": None,
        },
        "screenshotIds": [screenshot_id],
    }
    media = FakeSnapshot(
        media_id,
        {
            "appId": app_id,
            "mediaType": "COMMAND",
            "slot": "command",
            "filename": "game.cmd",
            "description": "Run",
            "contentType": "application/octet-stream",
            "objectPath": media_path,
            "size": 7,
            "sha256": media_sha,
        },
    )
    screenshot = FakeSnapshot(
        screenshot_id,
        {
            "appId": app_id,
            "filename": "screen.png",
            "contentType": "image/png",
            "objectPath": screenshot_path,
            "size": 10,
            "sha256": screenshot_sha,
        },
    )
    store = FakeObjectStore({media_path: b"command", screenshot_path: b"screenshot"})
    client = FakeFirestore(
        apps=(FakeSnapshot(app_id, app_document),),
        media=(media,),
        screenshots=(screenshot,),
    )
    catalog = staging.FirestoreAdminStagingCatalog(client, store)

    detail = catalog.get_app_detail(PUBLISHER, app_id)
    catalog.delete_app(identity=PUBLISHER, app_id=app_id, expected_revision=6)

    assert detail is not None
    assert [item.id for item in detail.media] == [media_id]
    assert [item.id for item in detail.screenshots] == [screenshot_id]
    assert client.transaction_value.deletes == [media_id, screenshot_id, app_id]
    assert store.deletes == [media_path, screenshot_path]
    audit = client.transaction_value.creates[0][1]
    assert audit["deletedMediaCount"] == 1
    assert audit["deletedScreenshotCount"] == 1

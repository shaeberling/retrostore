import pytest

import retrostore.admin.firmware as firmware
from retrostore.admin.assets import validate_firmware_upload
from retrostore.admin.auth import AdminIdentity

ADMIN = AdminIdentity("admin-1", "admin@example.test", "administrator")
PUBLISHER = AdminIdentity("publisher-1", "publisher@example.test", "publisher")


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

    def create(self, reference, value):
        self.creates.append((reference.id, value))

    def set(self, reference, value, *, merge=False):
        self.sets.append((reference.id, value, merge))


class FakeFirestore:
    def __init__(self, *, firmware_documents=(), tracks=()):
        self.collections = {
            "firmware": FakeCollection(
                {
                    snapshot.id: FakeDocument(snapshot.id, snapshot)
                    for snapshot in firmware_documents
                }
            ),
            "firmwareStagingTracks": FakeCollection(
                {
                    snapshot.id: FakeDocument(snapshot.id, snapshot)
                    for snapshot in tracks
                }
            ),
            "auditEvents": FakeCollection(),
        }
        self.transaction_value = FakeTransaction()

    def collection(self, name):
        return self.collections[name]

    def transaction(self):
        return self.transaction_value


class FakeObjectStore:
    def __init__(self, objects=None, after_put=None):
        self.objects = dict(objects or {})
        self.after_put = after_put
        self.puts = []
        self.deletes = []

    def put_verified(self, *, path, body, sha256, content_type):
        self.puts.append((path, body, sha256, content_type))
        created = path not in self.objects
        self.objects[path] = bytes(body)
        if self.after_put is not None:
            self.after_put()
        return created

    def read(self, path):
        return self.objects[path]

    def delete(self, path):
        self.deletes.append(path)
        self.objects.pop(path, None)


def _document(
    *, product="card", revision=1, version=1, status="STAGING", body=b"firmware"
):
    upload = validate_firmware_upload(filename="firmware.bin", body=body)
    return {
        "schemaVersion": 1,
        "status": status,
        "product": product,
        "revision": revision,
        "version": version,
        "filename": upload.filename,
        "contentType": upload.content_type,
        "objectPath": (
            f"firmware-staging/{product}/{revision}/{version}/{upload.sha256}.bin"
        ),
        "size": upload.size,
        "sha256": upload.sha256,
        "uploadedByUid": ADMIN.uid,
        "uploadedByEmail": ADMIN.email,
    }


def test_firmware_inventory_is_admin_only_sorted_and_staging_only() -> None:
    client = FakeFirestore(
        firmware_documents=(
            FakeSnapshot("card-1-1", _document()),
            FakeSnapshot("card-1-2", _document(version=2, body=b"newer")),
            FakeSnapshot(
                "trs-io-1-5",
                _document(product="trs-io", version=5, status="MIRRORED"),
            ),
        )
    )
    store = firmware.FirestoreAdminFirmwareStore(client, FakeObjectStore())

    records = store.list_firmware(ADMIN)

    assert [item.id for item in records] == ["card-1-2", "card-1-1"]
    with pytest.raises(firmware.FirmwareAuthorizationError):
        store.list_firmware(PUBLISHER)


def test_firmware_upload_allocates_next_version_and_audits_atomically(
    monkeypatch,
) -> None:
    monkeypatch.setattr(firmware.firestore, "transactional", lambda function: function)
    client = FakeFirestore(
        tracks=(FakeSnapshot("card-1", {"latestVersion": 2}),)
    )
    object_store = FakeObjectStore()
    store = firmware.FirestoreAdminFirmwareStore(client, object_store)
    upload = validate_firmware_upload(filename="C:\\uploads\\card.bin", body=b"v3")

    record = store.upload_firmware(
        identity=ADMIN,
        product="card",
        revision=1,
        upload=upload,
    )

    assert record.id == "card-1-3"
    assert record.version == 3
    expected_path = f"firmware-staging/card/1/3/{upload.sha256}.bin"
    assert record.object_path == expected_path
    assert object_store.puts == [
        (expected_path, b"v3", upload.sha256, "application/octet-stream")
    ]
    created = client.transaction_value.creates
    assert created[0][0] == "card-1-3"
    assert created[0][1]["status"] == "STAGING"
    assert created[1][1]["eventType"] == "STAGED_FIRMWARE_UPLOADED"
    assert client.transaction_value.sets[0][0] == "card-1"
    assert client.transaction_value.sets[0][1]["latestVersion"] == 3


def test_concurrent_firmware_upload_cleans_only_its_new_object(monkeypatch) -> None:
    monkeypatch.setattr(firmware.firestore, "transactional", lambda function: function)
    track = FakeSnapshot("trs-io-1", {"latestVersion": 4})
    client = FakeFirestore(tracks=(track,))

    def advance_track():
        track.value = {"latestVersion": 5}

    object_store = FakeObjectStore(after_put=advance_track)
    store = firmware.FirestoreAdminFirmwareStore(client, object_store)
    upload = validate_firmware_upload(filename="trs-io.bin", body=b"candidate")

    with pytest.raises(firmware.FirmwareConflictError, match="concurrently"):
        store.upload_firmware(
            identity=ADMIN,
            product="trs-io",
            revision=1,
            upload=upload,
        )

    assert object_store.deletes == [
        f"firmware-staging/trs-io/1/5/{upload.sha256}.bin"
    ]
    assert client.transaction_value.creates == []


def test_firmware_download_verifies_size_and_checksum() -> None:
    document = _document(body=b"verified firmware")
    snapshot = FakeSnapshot("card-1-1", document)
    object_store = FakeObjectStore({document["objectPath"]: b"verified firmware"})
    store = firmware.FirestoreAdminFirmwareStore(
        FakeFirestore(firmware_documents=(snapshot,)), object_store
    )

    result = store.read_firmware(ADMIN, "card-1-1")

    assert result is not None
    assert result[0].filename == "firmware.bin"
    assert result[1] == b"verified firmware"
    object_store.objects[document["objectPath"]] = b"tampered"
    with pytest.raises(ValueError, match="content verification"):
        store.read_firmware(ADMIN, "card-1-1")


@pytest.mark.parametrize("value", ("unknown", "", "CARD"))
def test_firmware_product_validation_rejects_unknown_values(value) -> None:
    with pytest.raises(ValueError, match="supported firmware product"):
        firmware.validate_firmware_product(value)


@pytest.mark.parametrize("value", ("-1", "65536", "one", True, None))
def test_firmware_revision_validation_is_bounded(value) -> None:
    with pytest.raises(ValueError, match="0 to 65535"):
        firmware.validate_firmware_revision(value)

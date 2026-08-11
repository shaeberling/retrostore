import hashlib
import json
from pathlib import Path

import pytest

from retrostore.migration.admin.reconcile_staging import (
    _checkpoint_id,
    _write_checkpoint,
    reconcile,
)


class FakeSnapshot:
    def __init__(self, document_id: str, value: dict):
        self.id = document_id
        self._value = value

    def to_dict(self):
        return self._value


class FakeQuery:
    def __init__(self, documents: list[FakeSnapshot], field: str, value: str):
        self._documents = documents
        self._field = field
        self._value = value

    def stream(self):
        return (
            document
            for document in self._documents
            if document.to_dict().get(self._field) == self._value
        )


class FakeCollection:
    def __init__(self, documents: list[FakeSnapshot]):
        self._documents = documents

    def where(self, *, filter):
        assert filter.op_string == "=="
        return FakeQuery(self._documents, filter.field_path, filter.value)


class FakeClient:
    def __init__(self, collections: dict[str, list[FakeSnapshot]]):
        self._collections = collections

    def collection(self, name: str):
        return FakeCollection(self._collections.get(name, []))


class FakeBlob:
    def __init__(self, name: str, body: bytes):
        self.name = name
        self._body = body

    def download_as_bytes(self):
        return self._body


class FakeBucket:
    def __init__(self, blobs: list[FakeBlob]):
        self._blobs = blobs

    def list_blobs(self, *, prefix: str):
        return (blob for blob in self._blobs if blob.name.startswith(prefix))


def test_checkpoint_is_private_and_bound_to_the_app_name(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint.json"
    _write_checkpoint(checkpoint, "Lifecycle", "app-id")

    assert checkpoint.stat().st_mode & 0o777 == 0o600
    assert _checkpoint_id(checkpoint, "Lifecycle") == "app-id"
    assert "Lifecycle" not in checkpoint.read_text()
    with pytest.raises(ValueError, match="another app name"):
        _checkpoint_id(checkpoint, "Another app")


def test_reconcile_verifies_links_content_order_audit_and_sanitizes_ids(
    tmp_path: Path,
) -> None:
    app_id = "11111111-1111-4111-8111-111111111111"
    media_id = "22222222-2222-4222-8222-222222222222"
    screenshot_id = "33333333-3333-4333-8333-333333333333"
    media_body = b"media"
    screenshot_body = b"\x89PNG\r\n\x1a\nimage"
    media_sha = hashlib.sha256(media_body).hexdigest()
    screenshot_sha = hashlib.sha256(screenshot_body).hexdigest()
    media_path = f"media/{app_id}/{media_id}/{media_sha}"
    screenshot_path = f"screenshots/{app_id}/{screenshot_id}/{screenshot_sha}.png"
    client = FakeClient(
        {
            "apps": [
                FakeSnapshot(
                    app_id,
                    {
                        "name": "Lifecycle",
                        "version": "1",
                        "description": "Test",
                        "model": "MODEL_I",
                        "categories": ["GAME"],
                        "releaseYear": 1981,
                        "authorId": "author-id",
                        "authorName": "Author",
                        "publisherUid": "private-uid",
                        "publisherEmail": "private@example.test",
                        "revision": 2,
                        "mediaSlots": {
                            "disks": [media_id, None, None, None],
                            "cassette": None,
                            "command": None,
                            "basic": None,
                        },
                        "screenshotIds": [screenshot_id],
                    },
                )
            ],
            "media": [
                FakeSnapshot(
                    media_id,
                    {
                        "appId": app_id,
                        "mediaType": "DISK",
                        "slot": "disk-1",
                        "filename": "image.dsk",
                        "description": "",
                        "contentType": "application/octet-stream",
                        "objectPath": media_path,
                        "size": len(media_body),
                        "sha256": media_sha,
                    },
                )
            ],
            "screenshots": [
                FakeSnapshot(
                    screenshot_id,
                    {
                        "appId": app_id,
                        "filename": "screen.png",
                        "contentType": "image/png",
                        "objectPath": screenshot_path,
                        "size": len(screenshot_body),
                        "sha256": screenshot_sha,
                    },
                )
            ],
            "auditEvents": [
                FakeSnapshot(
                    "audit-created",
                    {"targetId": app_id, "eventType": "STAGED_APP_CREATED"},
                ),
                FakeSnapshot(
                    "audit-media",
                    {
                        "appId": app_id,
                        "targetId": media_id,
                        "eventType": "STAGED_MEDIA_UPLOADED",
                        "revision": 2,
                    },
                ),
            ],
        }
    )
    bucket = FakeBucket(
        [FakeBlob(media_path, media_body), FakeBlob(screenshot_path, screenshot_body)]
    )

    report = reconcile(
        client=client,
        bucket=bucket,
        app_name="Lifecycle",
        checkpoint=tmp_path / "checkpoint.json",
        expected_media_filenames=("image.dsk",),
        expected_screenshot_filenames=("screen.png",),
        expected_event_types=("STAGED_APP_CREATED", "STAGED_MEDIA_UPLOADED"),
        expect_present=True,
    )

    assert report["all_checks_pass"] is True
    serialized = json.dumps(report)
    assert app_id not in serialized
    assert media_id not in serialized
    assert screenshot_id not in serialized
    assert "private-uid" not in serialized
    assert "private@example.test" not in serialized


def test_reconcile_accepts_an_atomic_import_as_revision_one(tmp_path: Path) -> None:
    app_id = "8c028afe-96b3-11e7-a68b-5b6133ca5f0c"
    client = FakeClient(
        {
            "apps": [
                FakeSnapshot(
                    app_id,
                    {
                        "name": "Imported Lifecycle",
                        "version": "1",
                        "description": "Test",
                        "model": "MODEL_I",
                        "categories": ["GAME"],
                        "releaseYear": 1981,
                        "authorId": "author-id",
                        "authorName": "Author",
                        "publisherUid": "private-uid",
                        "publisherEmail": "private@example.test",
                        "revision": 1,
                        "mediaSlots": {
                            "disks": [None, None, None, None],
                            "cassette": None,
                            "command": None,
                            "basic": None,
                        },
                        "screenshotIds": [],
                    },
                )
            ],
            "auditEvents": [
                FakeSnapshot(
                    "audit-import",
                    {
                        "targetId": app_id,
                        "eventType": "STAGED_RPK_IMPORTED",
                        "revision": 1,
                    },
                )
            ],
        }
    )

    report = reconcile(
        client=client,
        bucket=FakeBucket([]),
        app_name="Imported Lifecycle",
        checkpoint=tmp_path / "checkpoint.json",
        expected_media_filenames=(),
        expected_screenshot_filenames=(),
        expected_event_types=("STAGED_RPK_IMPORTED",),
        expect_present=True,
    )

    assert report["all_checks_pass"] is True
    assert report["audit"]["revisions"] == [1]

import hashlib

from retrostore.api_compat.canonical_storage import CanonicalCompatibilityStorage
from retrostore.api_compat.service import CompatibilityApi
from retrostore.api_compat.storage import InMemoryCompatibilityStorage
from retrostore.canonical_catalog import CanonicalCatalogRepository
from retrostore.generated import ApiProtos_pb2 as api_pb


def test_repository_reads_only_published_top_level_documents() -> None:
    client = FakeFirestore(_documents())
    repository = CanonicalCatalogRepository(client)

    apps = repository.list_apps()
    app = repository.get_app("app-1")

    assert [item.id for item in apps] == ["app-1"]
    assert app is not None
    assert app.name == "Armored Patrol"
    assert app.disk_media_ids == ("media-1", None, None, None)
    assert repository.get_app("draft-1") is None
    assert client.collections_streamed == ["apps"]


def test_media_references_and_regions_do_not_download_unneeded_objects() -> None:
    repository = CanonicalCatalogRepository(FakeFirestore(_documents()))
    reader = TrackingObjectReader(_objects())
    storage = CanonicalCompatibilityStorage(
        repository,
        reader,
        InMemoryCompatibilityStorage(),
        public_origin="https://retrostore.org",
    )
    api = CompatibilityApi(storage)

    entry = storage.get_catalog_entry("app-1")
    refs = api_pb.ApiResponseMediaImageRefs.FromString(
        api.fetch_media_image_refs(
            api_pb.FetchMediaImageRefsParams(app_id="app-1").SerializeToString()
        ).data
    )

    assert entry is not None
    assert entry.app.screenshot_url == ["https://retrostore.org/s/shot-1"]
    assert [(item.filename, item.size) for item in refs.mediaImageRef] == [
        ("game.dmk", 4),
        ("run.cmd", 3),
    ]
    assert reader.reads == []

    region = api.fetch_media_image_region(
        api_pb.FetchMediaImageRegionParams(
            token="app-1/game.dmk", start=1, length=2
        ).SerializeToString()
    )

    assert region.data == b"is"
    assert reader.reads == [("media/app-1/media-1/content", 1, 2)]


def test_full_media_screenshot_download_and_website_routes_are_lazy() -> None:
    repository = CanonicalCatalogRepository(FakeFirestore(_documents()))
    reader = TrackingObjectReader(_objects())
    storage = CanonicalCompatibilityStorage(
        repository,
        reader,
        InMemoryCompatibilityStorage(),
        public_origin="https://retrostore.org",
    )
    api = CompatibilityApi(storage)

    website = storage.list_website_apps()
    screenshot = storage.get_screenshot("shot-1")
    download = storage.get_download("app-1")

    assert website[0]["emulatorAppId"] == "app-1"
    assert reader.reads == []
    assert screenshot is not None
    assert screenshot.read_body() == b"png"
    assert download is not None
    assert [item.read_body() for item in download.media] == [b"disk", b"cmd"]

    response = api_pb.ApiResponseMediaImages.FromString(
        api.fetch_media_images(
            api_pb.FetchMediaImagesParams(app_id="app-1").SerializeToString()
        ).data
    )
    assert response.success is True
    assert [image.data for image in response.mediaImage if image.data] == [
        b"disk",
        b"cmd",
    ]


class FakeSnapshot:
    def __init__(self, document_id, value):
        self.id = document_id
        self.exists = value is not None
        self._value = value

    def to_dict(self):
        return None if self._value is None else dict(self._value)


class FakeReference:
    def __init__(self, client, collection, document_id):
        self.client = client
        self.collection = collection
        self.id = document_id

    def get(self):
        return FakeSnapshot(
            self.id, self.client.documents.get(self.collection, {}).get(self.id)
        )


class FakeCollection:
    def __init__(self, client, name):
        self.client = client
        self.name = name

    def stream(self):
        self.client.collections_streamed.append(self.name)
        return tuple(
            FakeSnapshot(document_id, value)
            for document_id, value in self.client.documents.get(self.name, {}).items()
        )

    def document(self, document_id):
        return FakeReference(self.client, self.name, document_id)


class FakeFirestore:
    def __init__(self, documents):
        self.documents = documents
        self.collections_streamed = []

    def collection(self, name):
        return FakeCollection(self, name)

    def get_all(self, references):
        return tuple(reference.get() for reference in references)


class TrackingObjectReader:
    def __init__(self, objects):
        self.objects = objects
        self.reads = []

    def read(self, descriptor, start=0, length=None):
        self.reads.append((descriptor.path, start, length))
        body = self.objects[descriptor.path]
        return body[start:] if length is None else body[start : start + length]


def _documents():
    disk, command, screenshot = _objects().values()
    return {
        "apps": {
            "app-1": {
                "schemaVersion": 1,
                "status": "PUBLISHED",
                "name": "Armored Patrol",
                "version": "1.0",
                "description": "Tank game",
                "platform": "TRS80",
                "model": "MODEL_I",
                "categories": ["GAME"],
                "releaseYear": 1981,
                "authorId": "author-1",
                "sourceAuthorId": "author-1",
                "authorName": "Jane Doe",
                "publisherEmail": "jane@example.test",
                "mediaSlots": {
                    "disks": ["media-1", None, None, None],
                    "cassette": None,
                    "command": "media-2",
                    "basic": None,
                },
                "screenshotIds": ["shot-1"],
                "firstPublishedAtMs": 1_000,
                "updatedAtMs": 2_000,
            },
            "draft-1": {
                "schemaVersion": 1,
                "status": "DRAFT",
            },
        },
        "media": {
            "media-1": _asset_document(
                app_id="app-1",
                media_type="DISK",
                slot="disk-1",
                filename="game.dmk",
                path="media/app-1/media-1/content",
                body=disk,
            ),
            "media-2": _asset_document(
                app_id="app-1",
                media_type="COMMAND",
                slot="command",
                filename="run.cmd",
                path="media/app-1/media-2/content",
                body=command,
            ),
        },
        "screenshots": {
            "shot-1": {
                "schemaVersion": 1,
                "appId": "app-1",
                "filename": "screen.png",
                "contentType": "image/png",
                "objectPath": "screenshots/app-1/shot-1/content",
                "size": len(screenshot),
                "sha256": hashlib.sha256(screenshot).hexdigest(),
                "uploadTimeMs": 5_000,
                "legacyServingUrl": None,
            }
        },
    }


def _asset_document(*, app_id, media_type, slot, filename, path, body):
    return {
        "schemaVersion": 1,
        "appId": app_id,
        "mediaType": media_type,
        "slot": slot,
        "filename": filename,
        "description": "",
        "contentType": "application/octet-stream",
        "objectPath": path,
        "size": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "uploadTimeMs": 4_000,
    }


def _objects():
    return {
        "media/app-1/media-1/content": b"disk",
        "media/app-1/media-2/content": b"cmd",
        "screenshots/app-1/shot-1/content": b"png",
    }

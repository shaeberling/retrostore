import hashlib
import struct

import pytest

from retrostore.api_compat.service import CompatibilityApi
from retrostore.generated import ApiProtos_pb2 as api_pb
from retrostore.mirror import CatalogMirror, MappingObjectReader, MirrorCompatibilityStorage

DISK = b"disk image"
COMMAND = b"command image"
SCREENSHOT = b"screenshot"


def _object(path: str, body: bytes) -> dict[str, object]:
    return {
        "object_path": path,
        "size": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def _manifest() -> dict[str, object]:
    return {
        "schema_version": 1,
        "source": {
            "project_id": "trs-80",
            "exported_at": "2026-08-06T20:00:00Z",
            "high_water_mark": "2026-08-06T19:59:59.999Z",
        },
        "apps": [
            {
                "id": "app-1",
                "name": "Armored Patrol",
                "version": "1.0",
                "description": "Tank game",
                "release_year": 1981,
                "platform": "TRS80",
                "model": "MODEL_I",
                "categories": ["GAME"],
                "author_id": "42",
                "author_name": "Jane Doe",
                "publisher_email": "publisher@example.test",
                "first_published_at_ms": 1_500_000_000_000,
                "updated_at_ms": 1_600_000_000_000,
                "media_slots": {
                    "disks": ["media-disk", None, None, None],
                    "cassette": None,
                    "command": "media-command",
                    "basic": None,
                },
                "screenshot_ids": ["shot-1"],
            }
        ],
        "media": [
            {
                "id": "media-disk",
                "app_id": "app-1",
                "media_type": "DISK",
                "filename": "game.dmk",
                "description": "Boot disk",
                "upload_time_ms": 1_600_000_000_001,
                **_object("media/app-1/media-disk/disk", DISK),
            },
            {
                "id": "media-command",
                "app_id": "app-1",
                "media_type": "COMMAND",
                "filename": "game.cmd",
                "description": "Executable",
                "upload_time_ms": 1_600_000_000_002,
                **_object("media/app-1/media-command/command", COMMAND),
            },
        ],
        "screenshots": [
            {
                "id": "shot-1",
                "app_id": "app-1",
                "filename": "screen.png",
                "content_type": "image/png",
                "upload_time_ms": 1_600_000_000_003,
                "legacy_serving_url": "https://legacy.example/shot-1",
                **_object("screenshots/app-1/shot-1/screen.png", SCREENSHOT),
            }
        ],
    }


def _reader(**overrides: bytes) -> MappingObjectReader:
    objects = {
        "media/app-1/media-disk/disk": DISK,
        "media/app-1/media-command/command": COMMAND,
        "screenshots/app-1/shot-1/screen.png": SCREENSHOT,
    }
    objects.update(overrides)
    return MappingObjectReader(objects)


def _reconciliation(objects: dict[str, bytes]) -> dict[str, object]:
    aggregate = hashlib.sha256()
    for path in sorted(objects):
        path_bytes = path.encode()
        body = objects[path]
        aggregate.update(struct.pack(">q", len(path_bytes)))
        aggregate.update(path_bytes)
        aggregate.update(struct.pack(">q", len(body)))
        aggregate.update(hashlib.sha256(body).digest())
    return {
        "app_count": 1,
        "media_count": 2,
        "screenshot_count": 1,
        "object_count": 3,
        "total_bytes": sum(len(body) for body in objects.values()),
        "content_aggregate_sha256": aggregate.hexdigest(),
    }


def test_normalized_mirror_reconstructs_catalog_order_and_binary_slots() -> None:
    mirror = CatalogMirror.from_dict(_manifest(), _reader())
    storage = MirrorCompatibilityStorage(
        mirror,
        screenshot_url=lambda screenshot: screenshot.legacy_serving_url or "",
    )

    entry = storage.get_catalog_entry("app-1")
    assert entry is not None
    assert entry.app == api_pb.App(
        id="app-1",
        name="Armored Patrol",
        version="1.0",
        description="Tank game",
        release_year=1981,
        author="Jane Doe",
        screenshot_url=["https://legacy.example/shot-1"],
        ext_trs80=api_pb.Trs80Extension(model=api_pb.MODEL_I),
    )
    assert entry.media_types == frozenset({api_pb.DISK, api_pb.COMMAND})
    assert storage.search_app_ids("tank") == {"app-1"}

    slots = storage.get_media_slots("app-1")
    assert [slot.media_type for slot in slots] == [
        api_pb.DISK,
        api_pb.DISK,
        api_pb.DISK,
        api_pb.DISK,
        api_pb.CASSETTE,
        api_pb.COMMAND,
        api_pb.BASIC,
    ]
    assert slots[0].image.data == DISK
    assert slots[0].image.type == api_pb.DISK
    assert slots[1].image == api_pb.MediaImage()
    assert slots[5].image.data == COMMAND


def test_normalized_mirror_drives_public_media_and_state_handlers() -> None:
    storage = MirrorCompatibilityStorage(CatalogMirror.from_dict(_manifest(), _reader()))
    api = CompatibilityApi(storage)

    media_response = api_pb.ApiResponseMediaImages.FromString(
        api.fetch_media_images(api_pb.FetchMediaImagesParams(app_id="app-1").SerializeToString()).data
    )
    assert media_response.success is True
    assert len(media_response.mediaImage) == 7
    assert media_response.mediaImage[0].data == DISK
    assert media_response.mediaImage[1] == api_pb.MediaImage()
    assert media_response.mediaImage[5].data == COMMAND

    state = api_pb.SystemState(
        model=api_pb.MODEL_I,
        memoryRegions=[api_pb.SystemState.MemoryRegion(start=100, data=b"state")],
    )
    upload = api_pb.ApiResponseUploadSystemState.FromString(
        api.upload_state(api_pb.UploadSystemStateParams(state=state).SerializeToString()).data
    )
    download = api_pb.ApiResponseDownloadSystemState.FromString(
        api.download_state(
            api_pb.DownloadSystemStateParams(token=upload.token).SerializeToString()
        ).data
    )
    assert upload.success is True
    assert download.systemState.memoryRegions[0].data == b"state"


def test_mirror_rejects_bad_checksum_and_cross_app_reference() -> None:
    with pytest.raises(ValueError, match="checksum mismatch"):
        CatalogMirror.from_dict(
            _manifest(),
            _reader(**{"media/app-1/media-disk/disk": b"disk imagf"}),
        )

    manifest = _manifest()
    manifest["media"][0]["app_id"] = "some-other-app"  # type: ignore[index]
    with pytest.raises(ValueError, match="belongs to"):
        CatalogMirror.from_dict(manifest, _reader())


def test_mirror_rejects_missing_reference_duplicate_id_and_unsafe_path() -> None:
    missing = _manifest()
    missing["apps"][0]["media_slots"]["command"] = "missing"  # type: ignore[index]
    with pytest.raises(ValueError, match="references missing media"):
        CatalogMirror.from_dict(missing, _reader())

    duplicate = _manifest()
    duplicate["media"].append(duplicate["media"][0])  # type: ignore[union-attr,index]
    with pytest.raises(ValueError, match="Duplicate media ID"):
        CatalogMirror.from_dict(duplicate, _reader())

    unsafe = _manifest()
    unsafe["media"][0]["object_path"] = "../outside"  # type: ignore[index]
    with pytest.raises(ValueError, match="normalized and relative"):
        CatalogMirror.from_dict(unsafe, _reader())


def test_mirror_independently_verifies_export_reconciliation() -> None:
    objects = dict(_reader().objects)
    manifest = _manifest()
    manifest["reconciliation"] = _reconciliation(objects)

    mirror = CatalogMirror.from_dict(manifest, MappingObjectReader(objects))

    assert mirror.source_project_id == "trs-80"

    manifest["reconciliation"]["total_bytes"] += 1  # type: ignore[index,operator]
    with pytest.raises(ValueError, match="total_bytes mismatch"):
        CatalogMirror.from_dict(manifest, MappingObjectReader(objects))

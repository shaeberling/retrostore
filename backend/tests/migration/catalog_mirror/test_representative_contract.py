import hashlib
import json
from pathlib import Path

import httpx

from retrostore.contract.compare_hosts import compare_captures
from retrostore.contract.observations import observe_response
from retrostore.contract.scenarios import all_safe_scenarios
from retrostore.generated import ApiProtos_pb2 as api_pb
from retrostore.migration.catalog_mirror import (
    CatalogMirror,
    MappingObjectReader,
    MirrorApiDataStore,
)
from retrostore.testing.api import representative_storage
from services.api.app import create_app

GOLDEN = Path(__file__).parents[2] / "contract" / "golden" / "live-safe-baseline.json"


def test_normalized_mirror_matches_all_reviewed_app_engine_observations() -> None:
    manifest, objects = _representative_mirror_export()
    mirror = CatalogMirror.from_dict(manifest, MappingObjectReader(objects))
    storage = MirrorApiDataStore(
        mirror,
        screenshot_url=lambda screenshot: screenshot.legacy_serving_url or "",
    )
    app = create_app({"TESTING": True, "RETROSTORE_API_STORAGE": storage})

    transport = httpx.WSGITransport(app=app)
    observations = []
    with httpx.Client(transport=transport, base_url="http://local.test") as client:
        for scenario in all_safe_scenarios():
            response = client.post(f"/api/{scenario.method.name}", content=scenario.body)
            observations.append(observe_response(scenario, response).to_dict())

    report = compare_captures(
        json.loads(GOLDEN.read_text()),
        {"base_url": "http://local.test", "observations": observations},
    )
    differences = [result for result in report["results"] if result["differences"]]
    assert report["summary"] == {
        "total": 45,
        "matching": 45,
        "different": 0,
    }, differences


def _representative_mirror_export() -> tuple[dict[str, object], dict[str, bytes]]:
    """Translate the reviewed fixture through the proposed language-neutral shape."""

    source = representative_storage()
    apps = []
    media = []
    screenshots = []
    objects = {}

    for entry in source.list_catalog_entries():
        app = entry.app
        slot_ids: list[str | None] = []
        for position, slot in enumerate(source.get_media_slots(app.id)):
            if not slot.image.data:
                slot_ids.append(None)
                continue
            media_id = f"{app.id}-media-{position}"
            object_path = f"media/{app.id}/{media_id}/content"
            body = bytes(slot.image.data)
            objects[object_path] = body
            media.append(
                {
                    "id": media_id,
                    "app_id": app.id,
                    "media_type": api_pb.MediaType.Name(slot.media_type),
                    "filename": slot.image.filename,
                    "description": slot.image.description,
                    "upload_time_ms": slot.image.uploadTime,
                    "object_path": object_path,
                    "size": len(body),
                    "sha256": hashlib.sha256(body).hexdigest(),
                }
            )
            slot_ids.append(media_id)
        slot_ids.extend([None] * (7 - len(slot_ids)))

        # The bounded representative fixture retains catalog media-presence flags for
        # two apps without bundling their unrelated media payloads. Materialize those
        # declared slots only in this test export; a real exporter must report a
        # dangling nonzero legacy media ID as an integrity failure.
        positions_by_type = {
            api_pb.DISK: 0,
            api_pb.CASSETTE: 4,
            api_pb.COMMAND: 5,
            api_pb.BASIC: 6,
        }
        for media_type in entry.media_types:
            position = positions_by_type[media_type]
            if slot_ids[position] is not None:
                continue
            media_id = f"{app.id}-fixture-presence-{position}"
            object_path = f"media/{app.id}/{media_id}/empty-fixture-placeholder"
            objects[object_path] = b""
            media.append(
                {
                    "id": media_id,
                    "app_id": app.id,
                    "media_type": api_pb.MediaType.Name(media_type),
                    "filename": "",
                    "description": "",
                    "upload_time_ms": 0,
                    "object_path": object_path,
                    "size": 0,
                    "sha256": hashlib.sha256(b"").hexdigest(),
                }
            )
            slot_ids[position] = media_id

        screenshot_ids = []
        for position, legacy_url in enumerate(app.screenshot_url):
            screenshot_id = f"{app.id}-screenshot-{position}"
            object_path = f"screenshots/{app.id}/{screenshot_id}/fixture"
            body = legacy_url.encode()
            objects[object_path] = body
            screenshots.append(
                {
                    "id": screenshot_id,
                    "app_id": app.id,
                    "filename": "fixture",
                    "content_type": "application/octet-stream",
                    "upload_time_ms": 0,
                    "legacy_serving_url": legacy_url,
                    "object_path": object_path,
                    "size": len(body),
                    "sha256": hashlib.sha256(body).hexdigest(),
                }
            )
            screenshot_ids.append(screenshot_id)

        apps.append(
            {
                "id": app.id,
                "name": app.name,
                "version": app.version,
                "description": app.description,
                "release_year": app.release_year,
                "platform": "TRS80",
                "model": api_pb.Trs80Model.Name(app.ext_trs80.model),
                "categories": [],
                "author_id": None,
                "author_name": app.author,
                "publisher_email": "",
                "first_published_at_ms": 0,
                "updated_at_ms": 0,
                "media_slots": {
                    "disks": slot_ids[:4],
                    "cassette": slot_ids[4],
                    "command": slot_ids[5],
                    "basic": slot_ids[6],
                },
                "screenshot_ids": screenshot_ids,
            }
        )

    return (
        {
            "schema_version": 1,
            "source": {
                "project_id": "representative-fixture",
                "exported_at": "2026-08-06T20:00:00Z",
                "high_water_mark": "fixture-v1",
            },
            "apps": apps,
            "media": media,
            "screenshots": screenshots,
        },
        objects,
    )

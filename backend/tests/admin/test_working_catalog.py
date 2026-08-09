import hashlib
from copy import deepcopy
from datetime import UTC, datetime

import pytest

from retrostore.admin.working_catalog import (
    WorkingCatalogMaterialization,
    build_working_catalog_candidate,
    build_working_catalog_materialization,
    working_materialization_to_mirror,
)
from retrostore.mirror import CatalogMirror, MappingObjectReader, build_catalog_snapshot
from tests.mirror.test_catalog import _manifest, _reader, _reconciliation


def _mirror() -> CatalogMirror:
    manifest = _manifest()
    manifest["apps"][0]["id"] = "0FA9D812-A861-45EA-AC89-D6442963EEFB"  # type: ignore[index]
    manifest["media"][0]["app_id"] = manifest["apps"][0]["id"]  # type: ignore[index]
    manifest["media"][1]["app_id"] = manifest["apps"][0]["id"]  # type: ignore[index]
    manifest["screenshots"][0]["app_id"] = manifest["apps"][0]["id"]  # type: ignore[index]
    manifest["apps"][0]["publisher_email"] = "legacy@example.test"  # type: ignore[index]
    manifest["reconciliation"] = _reconciliation(dict(_reader().objects))
    return CatalogMirror.from_dict(manifest, _reader())


def test_materialization_preserves_ids_metadata_and_does_not_assign_ownership() -> None:
    mirror = _mirror()
    snapshot = build_catalog_snapshot(mirror)

    result = build_working_catalog_materialization(mirror, snapshot)

    assert result.id == f"working-{result.manifest_sha256}"
    assert result.counts == {"apps": 1, "authors": 1, "media": 2, "screenshots": 1}
    app = result.collections["apps"]["0FA9D812-A861-45EA-AC89-D6442963EEFB"]
    assert app["publisherUid"] == ""
    assert app["publisherEmail"] == "legacy@example.test"
    assert app["firstPublishedAtMs"] == 1_500_000_000_000
    assert app["updatedAtMs"] == 1_600_000_000_000
    assert app["status"] == "PUBLISHED"
    assert app["mediaSlots"]["disks"] == ["media-disk", None, None, None]
    assert result.collections["media"]["media-disk"]["slot"] == "disk-1"
    screenshot = result.collections["screenshots"]["shot-1"]
    assert screenshot["position"] == 0
    assert screenshot["legacyServingUrl"] == "https://legacy.example/shot-1"
    assert all(
        document["sourceSnapshotId"] == snapshot.id
        for collection in result.collections.values()
        for document in collection.values()
    )


def test_materialized_working_set_round_trips_the_exact_published_mirror() -> None:
    mirror = _mirror()
    materialization = build_working_catalog_materialization(
        mirror, build_catalog_snapshot(mirror)
    )

    rebuilt = working_materialization_to_mirror(materialization, _reader())

    assert rebuilt.to_dict() == mirror.to_dict()
    assert build_catalog_snapshot(rebuilt).id == build_catalog_snapshot(mirror).id


def test_round_trip_rejects_tampered_source_document() -> None:
    mirror = _mirror()
    materialization = build_working_catalog_materialization(
        mirror, build_catalog_snapshot(mirror)
    )
    app_id = next(iter(materialization.collections["apps"]))
    collections = {
        name: {document_id: dict(document) for document_id, document in values.items()}
        for name, values in materialization.collections.items()
    }
    collections["apps"][app_id]["name"] = "Tampered"
    tampered = WorkingCatalogMaterialization(
        id=materialization.id,
        source=materialization.source,
        collections=collections,
        manifest_sha256=materialization.manifest_sha256,
    )

    with pytest.raises(ValueError, match="manifest"):
        working_materialization_to_mirror(tampered, _reader())


def test_materialization_rejects_unreferenced_metadata() -> None:
    manifest = _manifest()
    orphan = deepcopy(manifest["media"][0])  # type: ignore[index]
    orphan["id"] = "orphan"
    orphan["object_path"] = manifest["media"][0]["object_path"]  # type: ignore[index]
    manifest["media"].append(orphan)  # type: ignore[union-attr]
    manifest["reconciliation"] = None
    mirror = CatalogMirror.from_dict(manifest, _reader())

    with pytest.raises(ValueError, match="unreferenced media"):
        build_working_catalog_materialization(mirror, build_catalog_snapshot(mirror))


def _staged_changes():
    app_id = "11111111-1111-4111-8111-111111111111"
    media_id = "22222222-2222-4222-8222-222222222222"
    screenshot_id = "33333333-3333-4333-8333-333333333333"
    created = datetime(2026, 8, 10, 1, 2, 3, tzinfo=UTC)
    media_body = b"new disk"
    screenshot_body = b"new screenshot"
    media_sha = hashlib.sha256(media_body).hexdigest()
    screenshot_sha = hashlib.sha256(screenshot_body).hexdigest()
    media_path = f"media/{app_id}/{media_id}/{media_sha}"
    screenshot_path = (
        f"screenshots/{app_id}/{screenshot_id}/{screenshot_sha}.png"
    )
    return (
        {
            "apps": {
                app_id: {
                    "schemaVersion": 1,
                    "status": "STAGING",
                    "name": "New Game",
                    "version": "1.0",
                    "description": "A new staged game.",
                    "releaseYear": 1983,
                    "platform": "TRS80",
                    "model": "MODEL_III",
                    "categories": ["GAME"],
                    "authorId": "new-author",
                    "authorName": "New Author",
                    "publisherUid": "publisher-1",
                    "publisherEmail": "publisher@example.test",
                    "mediaSlots": {
                        "disks": [media_id, None, None, None],
                        "cassette": None,
                        "command": None,
                        "basic": None,
                    },
                    "screenshotIds": [screenshot_id],
                    "revision": 1,
                    "createdAt": created,
                    "updatedAt": created,
                    "firstPublishedAt": None,
                }
            },
            "authors": {
                "new-author": {
                    "schemaVersion": 1,
                    "displayName": "New Author",
                    "normalizedName": "new author",
                    "createdAt": created,
                }
            },
            "media": {
                media_id: {
                    "schemaVersion": 1,
                    "appId": app_id,
                    "mediaType": "DISK",
                    "slot": "disk-1",
                    "filename": "new.dmk",
                    "description": "Boot disk",
                    "contentType": "application/octet-stream",
                    "objectPath": media_path,
                    "size": len(media_body),
                    "sha256": media_sha,
                    "publisherUid": "publisher-1",
                    "createdAt": created,
                }
            },
            "screenshots": {
                screenshot_id: {
                    "schemaVersion": 1,
                    "appId": app_id,
                    "filename": "new.png",
                    "contentType": "image/png",
                    "objectPath": screenshot_path,
                    "size": len(screenshot_body),
                    "sha256": screenshot_sha,
                    "publisherUid": "publisher-1",
                    "position": 0,
                    "createdAt": created,
                }
            },
        },
        {media_path: media_body, screenshot_path: screenshot_body},
    )


def test_publication_candidate_merges_staged_new_apps_with_stable_screenshots() -> None:
    baseline_mirror = _mirror()
    baseline = build_working_catalog_materialization(
        baseline_mirror, build_catalog_snapshot(baseline_mirror)
    )
    staged, new_objects = _staged_changes()
    reader = MappingObjectReader({**dict(_reader().objects), **new_objects})

    candidate = build_working_catalog_candidate(baseline, staged, reader)

    assert len(candidate.apps) == 2
    new_app = next(app for app in candidate.apps if app.name == "New Game")
    assert new_app.disk_media_ids[0] in staged["media"]
    screenshot = candidate.screenshots[new_app.screenshot_ids[0]]
    assert screenshot.legacy_serving_url is None
    assert candidate.high_water_mark.startswith("working:")
    assert build_catalog_snapshot(candidate).id != build_catalog_snapshot(
        baseline_mirror
    ).id


def test_publication_candidate_without_changes_is_the_exact_baseline() -> None:
    mirror = _mirror()
    baseline = build_working_catalog_materialization(mirror, build_catalog_snapshot(mirror))
    empty = {name: {} for name in ("apps", "authors", "media", "screenshots")}

    candidate = build_working_catalog_candidate(baseline, empty, _reader())

    assert candidate.to_dict() == mirror.to_dict()


def test_publication_candidate_rejects_orphan_staged_assets() -> None:
    mirror = _mirror()
    baseline = build_working_catalog_materialization(mirror, build_catalog_snapshot(mirror))
    staged, new_objects = _staged_changes()
    staged["apps"] = {}

    with pytest.raises(ValueError, match="orphan documents"):
        build_working_catalog_candidate(
            baseline,
            staged,
            MappingObjectReader({**dict(_reader().objects), **new_objects}),
        )


def test_publication_candidate_overlays_published_metadata_copy_on_write() -> None:
    mirror = _mirror()
    baseline = build_working_catalog_materialization(mirror, build_catalog_snapshot(mirror))
    app_id = mirror.apps[0].id
    source = baseline.collections["apps"][app_id]
    created = datetime(2026, 8, 10, 2, 3, 4, tzinfo=UTC)
    draft = {
        **{
            key: deepcopy(value)
            for key, value in source.items()
            if key not in {"sourceKind", "sourceSnapshotId", "sourceFingerprint"}
        },
        "name": "Edited Published Game",
        "status": "DRAFT",
        "publisherUid": "admin-1",
        "baseSnapshotId": baseline.source["snapshotId"],
        "baseSourceFingerprint": source["sourceFingerprint"],
        "createdAt": created,
        "updatedAt": created,
    }
    changes = {
        "apps": {app_id: draft},
        "authors": {},
        "media": {},
        "screenshots": {},
    }

    candidate = build_working_catalog_candidate(baseline, changes, _reader())

    assert len(candidate.apps) == len(mirror.apps)
    edited = next(value for value in candidate.apps if value.id == app_id)
    assert edited.name == "Edited Published Game"
    assert edited.disk_media_ids == mirror.apps[0].disk_media_ids
    assert edited.screenshot_ids == mirror.apps[0].screenshot_ids
    assert candidate.media.keys() == mirror.media.keys()
    assert candidate.screenshots.keys() == mirror.screenshots.keys()
    assert build_catalog_snapshot(candidate).id != build_catalog_snapshot(mirror).id

    draft["baseSourceFingerprint"] = "b" * 64
    with pytest.raises(ValueError, match="another snapshot"):
        build_working_catalog_candidate(baseline, changes, _reader())

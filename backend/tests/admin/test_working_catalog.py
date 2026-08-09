from copy import deepcopy

import pytest

from retrostore.admin.working_catalog import (
    WorkingCatalogMaterialization,
    build_working_catalog_materialization,
    working_materialization_to_mirror,
)
from retrostore.mirror import CatalogMirror, build_catalog_snapshot
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

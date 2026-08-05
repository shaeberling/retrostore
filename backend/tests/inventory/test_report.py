import json
from datetime import UTC, datetime, timedelta

from retrostore.inventory.report import INVENTORY_KINDS, SourceEntity, build_inventory_report


class FakeSource:
    def __init__(self, entities: list[SourceEntity]) -> None:
        self._entities = entities

    def fetch_kind(self, kind: str) -> list[SourceEntity]:
        return [entity for entity in self._entities if entity.kind == kind]


def entity(kind: str, key: str | int, **properties: object) -> SourceEntity:
    return SourceEntity(kind=kind, key=key, properties=properties)


def test_report_is_sanitized_and_reconciles_legacy_references() -> None:
    now = datetime(2026, 8, 5, 12, tzinfo=UTC)
    source = FakeSource(
        [
            entity(
                "AppStoreItem",
                "private-app-id",
                listing={
                    "name": "Private title",
                    "description": "Private description",
                    "authorId": 1,
                    "publisherEmail": "publisher@example.com",
                },
                trs80Extension={"disk": [10, 999, 0, 0], "cassette": 0, "command": 0, "basic": 0},
                screenshotsBlobKeys=["blob-present", "blob-missing"],
            ),
            entity("Author", 1, name="Private author"),
            entity("RetroStoreUser", "publisher@example.com", firstName="Private"),
            entity("MediaImage", 10, appId="different-app", data=b"abc"),
            entity("MediaImage", 11, appId="missing-parent", data=b"12345"),
            entity(
                "SystemState",
                100,
                addTimestamp=int((now - timedelta(days=1)).timestamp() * 1000),
                memoryRegions=[{"start": 0, "data": b"ram"}],
            ),
            entity(
                "SystemState",
                101,
                addTimestamp=int((now - timedelta(days=8)).timestamp() * 1000),
                memoryRegions=[],
            ),
            entity("__BlobInfo__", "blob-present", size=3, md5_hash="digest"),
            entity("__BlobInfo__", "blob-orphan", size=5, md5_hash="digest"),
        ]
    )

    report = build_inventory_report(source, project="test-project", generated_at=now)

    assert report["totals"] == {"application_entities": 7, "records_scanned": 9}
    assert report["relationships"]["media"] == {
        "reference_count": 2,
        "unique_reference_count": 2,
        "missing_unique_reference_count": 1,
        "unreferenced_entity_count": 1,
        "ownership_mismatch_count": 1,
        "entity_with_missing_parent_count": 2,
    }
    assert report["relationships"]["screenshots"] == {
        "reference_count": 2,
        "unique_reference_count": 2,
        "missing_unique_blob_count": 1,
        "unreferenced_blob_count": 1,
    }
    assert report["system_states"]["active_count"] == 1
    assert report["system_states"]["expired_count"] == 1
    assert report["blobstore"]["total_bytes"] == 8
    assert report["kinds"]["MediaImage"]["binary_properties"]["data"]["total_bytes"] == 8
    assert (
        report["kinds"]["SystemState"]["binary_properties"]["memoryRegions[].data"][
            "total_bytes"
        ]
        == 3
    )
    assert report["kinds"]["RetroStoreUser"]["aggregate_sha256"] is None
    assert {item["code"] for item in report["findings"]["items"]} == {
        "media_missing_parent",
        "media_owner_mismatch",
        "missing_media",
        "missing_screenshot_blob",
        "orphaned_blob",
        "orphaned_media",
    }

    serialized = json.dumps(report)
    for private_value in (
        "private-app-id",
        "Private title",
        "Private description",
        "publisher@example.com",
        "Private author",
        "blob-present",
    ):
        assert private_value not in serialized


def test_report_digest_and_shapes_are_stable_across_source_order() -> None:
    now = datetime(2026, 8, 5, tzinfo=UTC)
    records = [
        entity("Author", 2, name="B"),
        entity("Author", 1, name="A"),
    ]

    first = build_inventory_report(FakeSource(records), project="test", generated_at=now)
    second = build_inventory_report(
        FakeSource(list(reversed(records))), project="test", generated_at=now
    )

    assert first["kinds"]["Author"] == second["kinds"]["Author"]
    assert first["kinds"]["Author"]["property_shapes"] == {
        "name": {"occurrences": 2, "types": {"string": 2}}
    }
    assert set(first["kinds"]) == set(INVENTORY_KINDS)


def test_report_rejects_naive_generation_time() -> None:
    source = FakeSource([])

    try:
        build_inventory_report(source, project="test", generated_at=datetime(2026, 8, 5))
    except ValueError as error:
        assert str(error) == "generated_at must be timezone-aware"
    else:
        raise AssertionError("Expected a naive datetime to be rejected")

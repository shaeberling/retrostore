import json
import stat
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from retrostore.inventory.classify_orphaned_blobs import (
    _verify_mirror_preservation,
    build_orphaned_blob_report,
    write_protected_report,
)
from retrostore.inventory.report import SourceEntity


def entity(kind: str, key: str, **properties: object) -> SourceEntity:
    return SourceEntity(kind=kind, key=key, properties=properties)


def test_classifies_unreferenced_blob_metadata_without_content() -> None:
    created = datetime(2026, 8, 10, 1, 2, tzinfo=UTC)
    apps = [
        entity(
            "AppStoreItem",
            "app",
            screenshotsBlobKeys=["referenced", "referenced"],
        )
    ]
    blobs = [
        entity(
            "__BlobInfo__",
            "referenced",
            size=3,
            md5_hash="same",
            content_type="image/png",
        ),
        entity("__BlobInfo__", "orphan-copy", size=3, md5_hash="same"),
        entity(
            "__BlobInfo__",
            "orphan-unique",
            size=5,
            md5_hash=b"unique",
            filename="old.png",
            creation=created,
        ),
        entity("__BlobInfo__", "orphan-unknown", size=7),
    ]

    report = build_orphaned_blob_report(
        apps,
        blobs,
        project="trs-80",
        generated_at=created,
        bundled_services_report={
            "safety": {"contains_blob_keys": False, "contains_binary_data": False},
            "blobstore": {
                "content_verified": True,
                "object_count": 4,
                "duplicate_key_count": 0,
                "total_bytes": 18,
                "bytes_hashed": 18,
                "objects_with_metadata_md5_count": 4,
                "metadata_md5_match_count": 4,
                "metadata_md5_mismatch_count": 0,
                "content_aggregate_sha256": "a" * 64,
            },
        },
    )

    assert report["safety"]["contains_blob_keys"] is True
    assert report["reconciliation"] == {
        "app_count": 1,
        "screenshot_reference_count": 2,
        "unique_screenshot_reference_count": 1,
        "blob_metadata_count": 4,
        "missing_referenced_blob_count": 0,
        "unreferenced_blob_count": 3,
    }
    assert report["classification"]["counts"] == {
        "content_duplicate_of_referenced": 1,
        "insufficient_metadata": 1,
        "unique_unreferenced_content": 1,
    }
    assert report["classification"]["total_bytes"] == 15
    assert report["classification"]["all_content_is_verified_referenced_duplicate"] is False
    by_key = {item["blob_key"]: item for item in report["objects"]}
    assert by_key["orphan-copy"]["referenced_content_match_count"] == 1
    assert by_key["orphan-copy"]["content_equivalence_verified"] is True
    assert by_key["orphan-copy"]["referenced_content_matches"][0]["app_id"] == "app"
    assert by_key["orphan-copy"]["referenced_content_matches"][0][
        "normalized_screenshot_id"
    ].startswith("screenshot-")
    assert by_key["orphan-unique"]["metadata_md5"] == b"unique".hex()
    assert by_key["orphan-unique"]["created_at"] == "2026-08-10T01:02:00+00:00"
    assert all(item["content_bytes_copied"] is False for item in report["objects"])


def test_rejects_missing_references_and_duplicate_metadata_keys() -> None:
    apps = [entity("AppStoreItem", "app", screenshotsBlobKeys=["missing"])]
    with pytest.raises(ValueError, match="1 references are missing"):
        build_orphaned_blob_report(apps, [], project="test")

    duplicate_blobs = [
        entity("__BlobInfo__", "same", size=1, md5_hash="a"),
        entity("__BlobInfo__", "same", size=1, md5_hash="a"),
    ]
    with pytest.raises(ValueError, match="Duplicate Blobstore metadata key"):
        build_orphaned_blob_report([], duplicate_blobs, project="test")


def test_rejects_unverified_bundled_services_evidence() -> None:
    report = {
        "safety": {"contains_blob_keys": False, "contains_binary_data": False},
        "blobstore": {
            "content_verified": True,
            "object_count": 1,
            "duplicate_key_count": 0,
            "total_bytes": 1,
            "bytes_hashed": 1,
            "objects_with_metadata_md5_count": 1,
            "metadata_md5_match_count": 0,
            "metadata_md5_mismatch_count": 1,
            "content_aggregate_sha256": "a" * 64,
        },
    }
    with pytest.raises(ValueError, match="metadata_md5_match_count"):
        build_orphaned_blob_report(
            [],
            [entity("__BlobInfo__", "blob", size=1, md5_hash="x")],
            project="test",
            bundled_services_report=report,
        )


def test_protected_writer_is_mode_0600_and_create_only(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    report = {"objects": [{"blob_key": "secret"}]}

    write_protected_report(report, output)

    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert json.loads(output.read_text()) == report
    with pytest.raises(FileExistsError):
        write_protected_report(report, output)


def test_verifies_duplicate_bytes_are_preserved_by_normalized_screenshot() -> None:
    body = b"same bytes"
    report = {
        "classification": {"all_content_is_verified_referenced_duplicate": True},
        "objects": [
            {
                "size": len(body),
                "metadata_md5": "b7c7a19ff9841101a57b7867181d267e",
                "referenced_content_matches": [
                    {"normalized_screenshot_id": "shot", "app_id": "app"}
                ],
            }
        ],
    }
    screenshot = SimpleNamespace(
        app_id="app", object=SimpleNamespace(path="screenshots/app/shot/content")
    )
    mirror = SimpleNamespace(
        screenshots={"shot": screenshot},
        object_bytes={"screenshots/app/shot/content": body},
    )

    result = _verify_mirror_preservation(report, mirror)  # type: ignore[arg-type]

    assert result == {
        "verified": True,
        "orphan_count": 1,
        "orphan_bytes": len(body),
        "unique_referenced_archive_object_count": 1,
        "all_orphan_content_preserved_in_archive": True,
        "additional_object_copy_required": False,
    }


def test_rejects_archive_that_does_not_preserve_duplicate_bytes() -> None:
    report = {
        "classification": {"all_content_is_verified_referenced_duplicate": True},
        "objects": [
            {
                "size": 4,
                "metadata_md5": "0" * 32,
                "referenced_content_matches": [
                    {"normalized_screenshot_id": "shot", "app_id": "app"}
                ],
            }
        ],
    }
    screenshot = SimpleNamespace(app_id="app", object=SimpleNamespace(path="path"))
    mirror = SimpleNamespace(screenshots={"shot": screenshot}, object_bytes={"path": b"bad"})

    with pytest.raises(ValueError, match="does not preserve"):
        _verify_mirror_preservation(report, mirror)  # type: ignore[arg-type]

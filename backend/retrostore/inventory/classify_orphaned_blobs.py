"""Create a protected metadata classification of unreferenced legacy blobs."""

import argparse
import hashlib
import json
import os
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from google.cloud.datastore.key import Key

from retrostore.inventory.datastore_source import create_datastore_source
from retrostore.inventory.report import SourceEntity
from retrostore.mirror import CatalogMirror, load_catalog_mirror_archive


def build_orphaned_blob_report(
    apps: Iterable[SourceEntity],
    blobs: Iterable[SourceEntity],
    *,
    project: str,
    database: str = "(default)",
    generated_at: datetime | None = None,
    bundled_services_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Reconcile screenshot references and classify orphan metadata.

    This deliberately operates only on Datastore metadata. Legacy Blobstore
    bytes remain readable only through the App Engine bundled service.
    """

    now = generated_at or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")
    now = now.astimezone(UTC)

    app_entities = list(apps)
    origins = _screenshot_reference_origins(app_entities)
    references = Counter(
        key for key, reference_origins in origins.items() for _ in reference_origins
    )
    blob_by_key: dict[str, SourceEntity] = {}
    for blob in blobs:
        key = _string_key(blob.key)
        if key in blob_by_key:
            raise ValueError("Duplicate Blobstore metadata key")
        blob_by_key[key] = blob

    missing = set(references) - set(blob_by_key)
    if missing:
        raise ValueError(f"Cannot classify blobs while {len(missing)} references are missing")

    referenced_keys = set(references)
    orphan_keys = sorted(set(blob_by_key) - referenced_keys)
    identities = {
        key: _content_identity(blob_by_key[key].properties) for key in blob_by_key
    }
    referenced_identity_counts = Counter(
        identities[key] for key in referenced_keys if identities[key] is not None
    )
    orphan_identity_counts = Counter(
        identities[key] for key in orphan_keys if identities[key] is not None
    )
    verification = _content_verification(bundled_services_report, blob_by_key)

    objects = []
    classification_counts: Counter[str] = Counter()
    for key in orphan_keys:
        blob = blob_by_key[key]
        identity = identities[key]
        if identity is None:
            classification = "insufficient_metadata"
        elif referenced_identity_counts[identity]:
            classification = "content_duplicate_of_referenced"
        elif orphan_identity_counts[identity] > 1:
            classification = "content_duplicate_only_among_orphans"
        else:
            classification = "unique_unreferenced_content"
        classification_counts[classification] += 1

        properties = blob.properties
        matches = []
        if identity is not None:
            for referenced_key in sorted(referenced_keys):
                if identities[referenced_key] != identity:
                    continue
                for origin in origins[referenced_key]:
                    matches.append(
                        {
                            "blob_key": referenced_key,
                            "blob_key_sha256": hashlib.sha256(
                                referenced_key.encode()
                            ).hexdigest(),
                            **origin,
                        }
                    )
        objects.append(
            {
                "blob_key": key,
                "blob_key_sha256": hashlib.sha256(key.encode()).hexdigest(),
                "size": _nonnegative_int(properties.get("size")),
                "content_type": _optional_string(properties.get("content_type")),
                "filename": _optional_string(properties.get("filename")),
                "created_at": _timestamp(properties.get("creation")),
                "metadata_md5": _md5_string(properties.get("md5_hash")),
                "classification": classification,
                "referenced_content_match_count": (
                    0 if identity is None else referenced_identity_counts[identity]
                ),
                "orphan_content_match_count": (
                    0 if identity is None else orphan_identity_counts[identity]
                ),
                "referenced_content_matches": matches,
                "content_equivalence_verified": bool(matches)
                and verification["all_metadata_md5_matches_content"],
                "content_bytes_copied": False,
            }
        )

    total_bytes = sum(
        size
        for key in orphan_keys
        if (size := _nonnegative_int(blob_by_key[key].properties.get("size"))) is not None
    )
    digest = hashlib.sha256()
    for item in objects:
        encoded = json.dumps(item, separators=(",", ":"), sort_keys=True).encode()
        digest.update(len(encoded).to_bytes(8, byteorder="big"))
        digest.update(encoded)

    return {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "source": {"project": project, "database": database},
        "safety": {
            "access_mode": "read-only",
            "contains_blob_keys": True,
            "contains_binary_data": False,
            "protected_local_artifact_required": True,
        },
        "reconciliation": {
            "app_count": len(app_entities),
            "screenshot_reference_count": sum(references.values()),
            "unique_screenshot_reference_count": len(references),
            "blob_metadata_count": len(blob_by_key),
            "missing_referenced_blob_count": 0,
            "unreferenced_blob_count": len(orphan_keys),
        },
        "classification": {
            "counts": dict(sorted(classification_counts.items())),
            "total_bytes": total_bytes,
            "all_objects_have_size": all(item["size"] is not None for item in objects),
            "all_objects_have_md5": all(item["metadata_md5"] is not None for item in objects),
            "object_metadata_aggregate_sha256": digest.hexdigest(),
            "all_content_is_verified_referenced_duplicate": all(
                item["content_equivalence_verified"] for item in objects
            ),
            "additional_content_fetch_required_for_preservation": any(
                not item["content_equivalence_verified"] for item in objects
            ),
        },
        "content_verification": verification,
        "objects": objects,
    }


def write_protected_report(report: Mapping[str, Any], output: Path) -> None:
    """Create a mode-0600 report without replacing an existing artifact."""

    body = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        output.unlink(missing_ok=True)
        raise


def verify_archive_preservation(
    report: Mapping[str, Any], archive: Path
) -> dict[str, Any]:
    """Prove that each orphan's verified duplicate bytes are in the catalog archive."""

    mirror = load_catalog_mirror_archive(archive)
    verification = _verify_mirror_preservation(report, mirror)
    archive_digest = hashlib.sha256()
    with archive.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            archive_digest.update(chunk)
    return {
        **verification,
        "archive_sha256": archive_digest.hexdigest(),
        "archive_bytes": archive.stat().st_size,
        "archive_source_project": mirror.source_project_id,
        "archive_exported_at": mirror.exported_at,
        "archive_high_water_mark": mirror.high_water_mark,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--confirm-project", required=True)
    parser.add_argument("--database", default="(default)")
    parser.add_argument("--auth", choices=("adc", "gcloud"), default="adc")
    parser.add_argument("--bundled-services-report", type=Path)
    parser.add_argument("--catalog-archive", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.confirm_project != args.project:
        raise ValueError("--confirm-project must exactly match --project")

    source = create_datastore_source(
        project=args.project,
        database=args.database,
        auth=args.auth,
    )
    apps = list(source.fetch_kind("AppStoreItem"))
    blobs = list(source.fetch_kind("__BlobInfo__"))
    bundled_services_report = None
    if args.bundled_services_report is not None:
        bundled_services_report = json.loads(args.bundled_services_report.read_text())
    report = build_orphaned_blob_report(
        apps,
        blobs,
        project=args.project,
        database=args.database,
        bundled_services_report=bundled_services_report,
    )
    if args.catalog_archive is not None:
        report["preservation"] = verify_archive_preservation(report, args.catalog_archive)
    write_protected_report(report, args.output)


def _screenshot_reference_origins(
    apps: Iterable[SourceEntity],
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for app in apps:
        app_id = _string_app_key(app.key)
        values = app.properties.get("screenshotsBlobKeys")
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes, bytearray)):
            for order, value in enumerate(values):
                if isinstance(value, str) and value:
                    digest = hashlib.sha256()
                    digest.update(app_id.encode())
                    digest.update(b"\0")
                    digest.update(value.encode())
                    result.setdefault(value, []).append(
                        {
                            "app_id": app_id,
                            "screenshot_order": order,
                            "normalized_screenshot_id": f"screenshot-{digest.hexdigest()}",
                        }
                    )
    return result


def _string_key(value: Any) -> str:
    key_value = value.id_or_name if isinstance(value, Key) else value
    if not isinstance(key_value, str) or not key_value:
        raise ValueError("Blobstore metadata key must be a non-empty string")
    return key_value


def _string_app_key(value: Any) -> str:
    key_value = value.id_or_name if isinstance(value, Key) else value
    if not isinstance(key_value, str) or not key_value:
        raise ValueError("App entity key must be a non-empty string")
    return key_value


def _content_verification(
    report: Mapping[str, Any] | None, blobs: Mapping[str, SourceEntity]
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "bundled_services_report_supplied": report is not None,
        "all_metadata_md5_matches_content": False,
        "source_report_sha256": None,
        "content_aggregate_sha256": None,
    }
    if report is None:
        return result

    encoded = json.dumps(report, separators=(",", ":"), sort_keys=True).encode()
    result["source_report_sha256"] = hashlib.sha256(encoded).hexdigest()
    safety = report.get("safety")
    blobstore = report.get("blobstore")
    if not isinstance(safety, Mapping) or not isinstance(blobstore, Mapping):
        raise ValueError("Bundled-services report is malformed")
    contains_keys = safety.get("contains_blob_keys")
    contains_binary = safety.get("contains_binary_data")
    if contains_keys is not False or contains_binary is not False:
        raise ValueError("Bundled-services report is not sanitized")

    object_count = len(blobs)
    total_bytes = sum(
        size
        for blob in blobs.values()
        if (size := _nonnegative_int(blob.properties.get("size"))) is not None
    )
    expected = {
        "content_verified": True,
        "object_count": object_count,
        "duplicate_key_count": 0,
        "total_bytes": total_bytes,
        "bytes_hashed": total_bytes,
        "objects_with_metadata_md5_count": object_count,
        "metadata_md5_match_count": object_count,
        "metadata_md5_mismatch_count": 0,
    }
    for field, value in expected.items():
        if blobstore.get(field) != value:
            raise ValueError(f"Bundled-services report has unexpected {field}")
    content_digest = blobstore.get("content_aggregate_sha256")
    if not isinstance(content_digest, str) or len(content_digest) != 64:
        raise ValueError("Bundled-services report has no valid content aggregate")
    result["all_metadata_md5_matches_content"] = True
    result["content_aggregate_sha256"] = content_digest
    return result


def _content_identity(properties: Mapping[str, Any]) -> tuple[int, str] | None:
    size = _nonnegative_int(properties.get("size"))
    md5 = _md5_string(properties.get("md5_hash"))
    return None if size is None or md5 is None else (size, md5)


def _nonnegative_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _md5_string(value: Any) -> str | None:
    if isinstance(value, bytes):
        return value.hex()
    return _optional_string(value)


def _timestamp(value: Any) -> str | None:
    if not isinstance(value, datetime):
        return None
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.astimezone(UTC).isoformat()


def _verify_mirror_preservation(
    report: Mapping[str, Any], mirror: CatalogMirror
) -> dict[str, Any]:
    classification = report.get("classification")
    objects = report.get("objects")
    if not isinstance(classification, Mapping) or not isinstance(objects, list):
        raise ValueError("Orphaned-blob report is malformed")
    if classification.get("all_content_is_verified_referenced_duplicate") is not True:
        raise ValueError("Orphan content equivalence has not been verified")

    preserved_paths: set[str] = set()
    preserved_bytes = 0
    for item in objects:
        if not isinstance(item, Mapping):
            raise ValueError("Orphaned-blob report object is malformed")
        expected_md5 = item.get("metadata_md5")
        expected_size = item.get("size")
        matches = item.get("referenced_content_matches")
        if not isinstance(expected_md5, str) or not isinstance(expected_size, int):
            raise ValueError("Orphaned-blob report object has incomplete metadata")
        if not isinstance(matches, list) or not matches:
            raise ValueError("Orphaned-blob report object has no preservation source")

        matching_paths: set[str] = set()
        for match in matches:
            if not isinstance(match, Mapping):
                raise ValueError("Orphan preservation match is malformed")
            screenshot_id = match.get("normalized_screenshot_id")
            app_id = match.get("app_id")
            if not isinstance(screenshot_id, str) or not isinstance(app_id, str):
                raise ValueError("Orphan preservation match has invalid identifiers")
            screenshot = mirror.screenshots.get(screenshot_id)
            if screenshot is None or screenshot.app_id != app_id:
                continue
            body = mirror.object_bytes[screenshot.object.path]
            body_md5 = hashlib.md5(body, usedforsecurity=False).hexdigest()
            if len(body) == expected_size and body_md5 == expected_md5.lower():
                matching_paths.add(screenshot.object.path)
        if not matching_paths:
            raise ValueError("Catalog archive does not preserve an orphan's duplicate bytes")
        preserved_paths.update(matching_paths)
        preserved_bytes += expected_size

    return {
        "verified": True,
        "orphan_count": len(objects),
        "orphan_bytes": preserved_bytes,
        "unique_referenced_archive_object_count": len(preserved_paths),
        "all_orphan_content_preserved_in_archive": True,
        "additional_object_copy_required": False,
    }


if __name__ == "__main__":
    main()

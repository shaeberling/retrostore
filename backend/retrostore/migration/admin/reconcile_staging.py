"""Read-only reconciliation for an isolated staged-app lifecycle."""

import argparse
import hashlib
import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from google.cloud import firestore, storage
from google.cloud.firestore_v1.base_query import FieldFilter

from retrostore.admin.apps import (
    _app_record,
    _document_data,
    _media_record,
    _ordered_media_ids,
    _screenshot_record,
)
from retrostore.google_cloud import gcloud_impersonated_credentials


def _documents(client: firestore.Client, collection: str, field: str, value: str) -> list[Any]:
    return list(
        client.collection(collection).where(filter=FieldFilter(field, "==", value)).stream()
    )


def _checkpoint_id(path: Path, app_name: str) -> str | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("app_name_sha256") != hashlib.sha256(app_name.encode()).hexdigest():
        raise ValueError("Staging checkpoint belongs to another app name")
    app_id = value.get("app_id")
    if not isinstance(app_id, str) or not app_id:
        raise ValueError("Staging checkpoint has no app identifier")
    return app_id


def _write_checkpoint(path: Path, app_name: str, app_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "app_name_sha256": hashlib.sha256(app_name.encode()).hexdigest(),
                "app_id": app_id,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    os.chmod(path, 0o600)


def reconcile(
    *,
    client: firestore.Client,
    bucket: storage.Bucket,
    app_name: str,
    checkpoint: Path,
    expected_media_filenames: tuple[str, ...],
    expected_screenshot_filenames: tuple[str, ...],
    expected_event_types: tuple[str, ...],
    expect_present: bool,
) -> dict[str, Any]:
    matches = _documents(client, "apps", "name", app_name)
    if len(matches) > 1:
        raise ValueError("More than one staged app has the requested exact name")
    app_id = matches[0].id if matches else _checkpoint_id(checkpoint, app_name)
    if app_id is None:
        raise ValueError("Staged app was not found and no checkpoint exists")
    if matches:
        _write_checkpoint(checkpoint, app_name, app_id)

    app = _app_record(matches[0].id, _document_data(matches[0])) if matches else None
    media_documents = _documents(client, "media", "appId", app_id)
    screenshot_documents = _documents(client, "screenshots", "appId", app_id)
    media_by_id = {
        document.id: _media_record(document.id, _document_data(document))
        for document in media_documents
    }
    screenshots_by_id = {
        document.id: _screenshot_record(document.id, _document_data(document))
        for document in screenshot_documents
    }

    if app is None:
        ordered_media = ()
        ordered_screenshots = ()
    else:
        ordered_media = tuple(media_by_id[item] for item in _ordered_media_ids(app))
        ordered_screenshots = tuple(screenshots_by_id[item] for item in app.screenshot_ids)

    linked_paths = {
        item.object_path: (item.size, item.sha256)
        for item in (*ordered_media, *ordered_screenshots)
    }
    prefix_blobs = {
        blob.name: blob
        for prefix in (f"media/{app_id}/", f"screenshots/{app_id}/")
        for blob in bucket.list_blobs(prefix=prefix)
    }
    verified_bytes = 0
    verified_hashes: list[str] = []
    content_verified = True
    for path, (expected_size, expected_sha256) in linked_paths.items():
        blob = prefix_blobs.get(path)
        if blob is None:
            content_verified = False
            continue
        body = blob.download_as_bytes()
        actual_sha256 = hashlib.sha256(body).hexdigest()
        content_verified &= len(body) == expected_size and actual_sha256 == expected_sha256
        verified_bytes += len(body)
        verified_hashes.append(actual_sha256)

    audit_documents = {
        document.id: document
        for field in ("appId", "targetId")
        for document in _documents(client, "auditEvents", field, app_id)
    }
    audit_values = [_document_data(document) for document in audit_documents.values()]
    event_types = Counter(
        value.get("eventType") for value in audit_values if isinstance(value.get("eventType"), str)
    )
    revisions = sorted(
        value["revision"] for value in audit_values if isinstance(value.get("revision"), int)
    )
    first_revision = 1 if 1 in revisions else 2
    last_revision = app.revision if app else max(revisions, default=1)
    expected_revisions = list(range(first_revision, last_revision + 1))

    checks = {
        "presence_matches": (app is not None) == expect_present,
        "linked_media_documents_match": (
            set(media_by_id) == set(_ordered_media_ids(app)) if app else not media_by_id
        ),
        "linked_screenshot_documents_match": (
            set(screenshots_by_id) == set(app.screenshot_ids) if app else not screenshots_by_id
        ),
        "storage_prefix_matches_links": set(prefix_blobs) == set(linked_paths),
        "linked_content_verified": content_verified,
        "media_filenames_match": tuple(item.filename for item in ordered_media)
        == expected_media_filenames,
        "screenshot_order_matches": tuple(item.filename for item in ordered_screenshots)
        == expected_screenshot_filenames,
        "audit_event_types_match": event_types == Counter(expected_event_types),
        "revision_chain_contiguous": revisions == expected_revisions,
    }
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "safety": {
            "access_mode": "read-only",
            "contains_document_ids": False,
            "contains_object_paths": False,
            "contains_account_identifiers": False,
        },
        "app": {
            "present": app is not None,
            "revision": app.revision if app else None,
            "media_document_count": len(media_by_id),
            "screenshot_document_count": len(screenshots_by_id),
        },
        "storage": {
            "prefix_object_count": len(prefix_blobs),
            "linked_object_count": len(linked_paths),
            "verified_bytes": verified_bytes,
            "content_aggregate_sha256": hashlib.sha256(
                "".join(sorted(verified_hashes)).encode()
            ).hexdigest(),
        },
        "audit": {
            "event_count": sum(event_types.values()),
            "event_types": dict(sorted(event_types.items())),
            "revisions": revisions,
        },
        "checks": checks,
        "all_checks_pass": all(checks.values()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--impersonate-service-account", required=True)
    parser.add_argument("--app-name", required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--expect-present", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--expect-media-filename", action="append", default=[])
    parser.add_argument("--expect-screenshot-filename", action="append", default=[])
    parser.add_argument("--expect-event-type", action="append", default=[])
    args = parser.parse_args()

    credentials = gcloud_impersonated_credentials(
        project=args.project,
        service_account=args.impersonate_service_account,
    )
    client = firestore.Client(
        project=args.project,
        database=args.database,
        credentials=credentials,
    )
    bucket = storage.Client(project=args.project, credentials=credentials).bucket(args.bucket)
    report = reconcile(
        client=client,
        bucket=bucket,
        app_name=args.app_name,
        checkpoint=args.checkpoint,
        expected_media_filenames=tuple(args.expect_media_filename),
        expected_screenshot_filenames=tuple(args.expect_screenshot_filename),
        expected_event_types=tuple(args.expect_event_type),
        expect_present=args.expect_present,
    )
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    raise SystemExit(0 if report["all_checks_pass"] else 1)


if __name__ == "__main__":
    main()

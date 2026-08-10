"""Create a protected read-only reconciliation of legacy and Firebase users."""

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import firebase_admin
from google.cloud import firestore
from google.cloud.datastore.key import Key
from google.oauth2.credentials import Credentials

from retrostore.admin.users import (
    AdminUser,
    FirebaseAdminUserDirectory,
    FirestoreAdminRoleStore,
)
from retrostore.inventory.classify_orphaned_blobs import write_protected_report
from retrostore.inventory.datastore_source import (
    create_datastore_source,
    gcloud_credentials,
)
from retrostore.inventory.report import SourceEntity

_LEGACY_ROLES = frozenset({"ADMIN", "PUBLISHER", "USER", "NO_ACCOUNT"})
_MODERN_ROLE = {"ADMIN": "administrator", "PUBLISHER": "publisher"}


def build_legacy_user_report(
    legacy_users: Iterable[SourceEntity],
    apps: Iterable[SourceEntity],
    firebase_users: Iterable[AdminUser],
    *,
    project: str,
    legacy_database: str = "(default)",
    admin_database: str = "retrostore",
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Reconcile identity and role state without selecting a migration policy."""

    now = generated_at or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")
    now = now.astimezone(UTC)

    legacy_by_email = _legacy_users_by_email(legacy_users)
    firebase = tuple(firebase_users)
    firebase_by_email = _firebase_users_by_email(firebase)
    publisher_counts = _publisher_counts(apps)
    missing_publishers = set(publisher_counts) - set(legacy_by_email)
    if missing_publishers:
        raise ValueError(
            f"Cannot classify users while {len(missing_publishers)} publishers are missing"
        )

    objects: list[dict[str, Any]] = []
    classification_counts: Counter[str] = Counter()
    role_counts: Counter[str] = Counter()
    for normalized_email in sorted(legacy_by_email):
        email, entity = legacy_by_email[normalized_email]
        legacy_role = _legacy_role(entity.properties.get("type"))
        target_role = _MODERN_ROLE.get(legacy_role)
        role_counts[legacy_role] += 1
        matches = firebase_by_email.get(normalized_email, ())
        classification = _classification(target_role, matches)
        classification_counts[classification] += 1
        objects.append(
            {
                "email": email,
                "email_sha256": hashlib.sha256(normalized_email.encode()).hexdigest(),
                "first_name": _optional_string(entity.properties.get("firstName")),
                "last_name": _optional_string(entity.properties.get("lastName")),
                "legacy_role": legacy_role,
                "direct_modern_role": target_role,
                "published_app_count": publisher_counts.get(normalized_email, 0),
                "firebase_matches": [
                    {
                        "uid": user.uid,
                        "email": user.email,
                        "email_verified": user.email_verified,
                        "disabled": user.disabled,
                        "role": user.role,
                        "providers": list(user.providers),
                    }
                    for user in matches
                ],
                "classification": classification,
                "migration_action_selected": False,
            }
        )

    matching_count = sum(bool(item["firebase_matches"]) for item in objects)
    published_user_count = sum(item["published_app_count"] > 0 for item in objects)
    direct_role_count = sum(item["direct_modern_role"] is not None for item in objects)
    direct_role_without_firebase_count = sum(
        item["direct_modern_role"] is not None and not item["firebase_matches"]
        for item in objects
    )
    attribution_only_count = sum(
        item["direct_modern_role"] is None and item["published_app_count"] > 0
        for item in objects
    )
    unreferenced_without_role_count = sum(
        item["direct_modern_role"] is None and item["published_app_count"] == 0
        for item in objects
    )
    firebase_role_counts = Counter(user.role or "none" for user in firebase)
    digest = hashlib.sha256()
    for item in objects:
        encoded = json.dumps(item, separators=(",", ":"), sort_keys=True).encode()
        digest.update(len(encoded).to_bytes(8, byteorder="big"))
        digest.update(encoded)

    return {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "source": {
            "project": project,
            "legacy_database": legacy_database,
            "admin_database": admin_database,
        },
        "safety": {
            "access_mode": "read-only",
            "contains_email_addresses": True,
            "contains_firebase_uids": True,
            "contains_credentials": False,
            "protected_local_artifact_required": True,
            "migration_action_selected": False,
        },
        "summary": {
            "legacy_user_count": len(objects),
            "legacy_role_counts": dict(sorted(role_counts.items())),
            "published_app_count": sum(publisher_counts.values()),
            "legacy_user_with_published_apps_count": published_user_count,
            "legacy_user_with_direct_modern_role_count": direct_role_count,
            "legacy_direct_role_without_firebase_count": (
                direct_role_without_firebase_count
            ),
            "legacy_attribution_only_count": attribution_only_count,
            "legacy_unreferenced_without_modern_role_count": (
                unreferenced_without_role_count
            ),
            "firebase_identity_count": len(firebase),
            "firebase_role_counts": dict(sorted(firebase_role_counts.items())),
            "legacy_user_matching_firebase_count": matching_count,
            "legacy_user_without_firebase_count": len(objects) - matching_count,
            "firebase_identity_without_legacy_user_count": len(firebase) - matching_count,
            "classification_counts": dict(sorted(classification_counts.items())),
            "identity_aggregate_sha256": digest.hexdigest(),
        },
        "users": objects,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--confirm-project", required=True)
    parser.add_argument("--legacy-database", default="(default)")
    parser.add_argument("--admin-database", default="retrostore")
    parser.add_argument("--auth", choices=("gcloud",), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.confirm_project != args.project:
        raise ValueError("--confirm-project must exactly match --project")
    credentials = gcloud_credentials(quota_project=args.project)
    source = create_datastore_source(
        project=args.project,
        database=args.legacy_database,
        auth=args.auth,
    )
    legacy_users = list(source.fetch_kind("RetroStoreUser"))
    apps = list(source.fetch_kind("AppStoreItem"))

    role_store = FirestoreAdminRoleStore(
        firestore.Client(
            project=args.project,
            database=args.admin_database,
            credentials=credentials,
        )
    )
    firebase_app = _firebase_app(args.project, credentials)
    directory = FirebaseAdminUserDirectory(
        args.project,
        app=firebase_app,
        role_store=role_store,
    )
    report = build_legacy_user_report(
        legacy_users,
        apps,
        directory.list_users(),
        project=args.project,
        legacy_database=args.legacy_database,
        admin_database=args.admin_database,
    )
    write_protected_report(report, args.output)
    return 0


def _legacy_users_by_email(
    users: Iterable[SourceEntity],
) -> dict[str, tuple[str, SourceEntity]]:
    result: dict[str, tuple[str, SourceEntity]] = {}
    for entity in users:
        email = _entity_string_key(entity.key, "Legacy user")
        property_email = entity.properties.get("email")
        if property_email is not None and property_email != email:
            raise ValueError("Legacy user key and email property differ")
        normalized = _normalized_email(email)
        if normalized in result:
            raise ValueError("Legacy user emails are not unique case-insensitively")
        result[normalized] = (email, entity)
    return result


def _firebase_users_by_email(
    users: Iterable[AdminUser],
) -> dict[str, tuple[AdminUser, ...]]:
    grouped: dict[str, list[AdminUser]] = {}
    for user in users:
        if not user.email:
            continue
        grouped.setdefault(_normalized_email(user.email), []).append(user)
    duplicates = [email for email, matches in grouped.items() if len(matches) > 1]
    if duplicates:
        raise ValueError("Firebase emails are not unique case-insensitively")
    return {email: tuple(matches) for email, matches in grouped.items()}


def _publisher_counts(apps: Iterable[SourceEntity]) -> Counter[str]:
    result: Counter[str] = Counter()
    for app in apps:
        listing = app.properties.get("listing")
        if not isinstance(listing, Mapping):
            raise ValueError("App listing is missing while classifying publishers")
        email = listing.get("publisherEmail")
        if not isinstance(email, str) or not email:
            raise ValueError("App publisher email is missing")
        result[_normalized_email(email)] += 1
    return result


def _legacy_role(value: Any) -> str:
    role = "NO_ACCOUNT" if value is None else value
    if not isinstance(role, str) or role not in _LEGACY_ROLES:
        raise ValueError("Legacy user role is unsupported")
    return role


def _classification(target_role: str | None, matches: tuple[AdminUser, ...]) -> str:
    if not matches:
        return (
            "unmatched_with_direct_modern_role"
            if target_role is not None
            else "unmatched_without_direct_modern_role"
        )
    current_role = matches[0].role
    if current_role == target_role:
        return "matched_role_equivalent"
    if current_role is None:
        return "matched_without_modern_role"
    if target_role is None:
        return "matched_with_no_direct_legacy_mapping"
    return "matched_role_mismatch"


def _entity_string_key(value: Any, label: str) -> str:
    key_value = value.id_or_name if isinstance(value, Key) else value
    if not isinstance(key_value, str) or not key_value:
        raise ValueError(f"{label} key must be a non-empty string")
    return key_value


def _normalized_email(value: str) -> str:
    normalized = value.strip().casefold()
    if not normalized or "@" not in normalized:
        raise ValueError("User email is malformed")
    return normalized


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Legacy user name is malformed")
    return value


def _firebase_app(project: str, credentials: Credentials) -> firebase_admin.App:
    name = f"retrostore-user-inventory-{project}"
    try:
        return firebase_admin.get_app(name)
    except ValueError:
        return firebase_admin.initialize_app(
            credential=credentials,
            options={"projectId": project},
            name=name,
        )


if __name__ == "__main__":
    raise SystemExit(main())

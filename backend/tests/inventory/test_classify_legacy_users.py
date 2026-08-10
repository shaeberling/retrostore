import json
import stat
from datetime import UTC, datetime

import pytest

from retrostore.admin.users import AdminUser
from retrostore.inventory.classify_legacy_users import build_legacy_user_report
from retrostore.inventory.classify_orphaned_blobs import write_protected_report
from retrostore.inventory.report import SourceEntity


def entity(kind: str, key: str, **properties: object) -> SourceEntity:
    return SourceEntity(kind=kind, key=key, properties=properties)


def firebase_user(
    uid: str,
    email: str,
    *,
    role: str | None = None,
    verified: bool = True,
    disabled: bool = False,
) -> AdminUser:
    return AdminUser(
        uid=uid,
        email=email,
        email_verified=verified,
        disabled=disabled,
        role=role,
        providers=("google.com",),
    )


def test_reconciles_legacy_publishers_and_modern_roles() -> None:
    now = datetime(2026, 8, 10, tzinfo=UTC)
    users = [
        entity(
            "RetroStoreUser",
            "Admin@Example.test",
            email="Admin@Example.test",
            firstName="Admin",
            lastName="User",
            type="ADMIN",
        ),
        entity("RetroStoreUser", "publisher@example.test", type="PUBLISHER"),
        entity("RetroStoreUser", "viewer@example.test", type="USER"),
    ]
    apps = [
        entity(
            "AppStoreItem",
            "app-1",
            listing={"publisherEmail": "PUBLISHER@example.test"},
        ),
        entity(
            "AppStoreItem",
            "app-2",
            listing={"publisherEmail": "publisher@example.test"},
        ),
    ]
    firebase = [
        firebase_user("admin", "admin@example.test", role="administrator"),
        firebase_user("publisher", "publisher@example.test"),
        firebase_user("other", "other@example.test", role="publisher"),
    ]

    report = build_legacy_user_report(
        users,
        apps,
        firebase,
        project="trs-80",
        generated_at=now,
    )

    assert report["summary"] == {
        "legacy_user_count": 3,
        "legacy_role_counts": {"ADMIN": 1, "PUBLISHER": 1, "USER": 1},
        "published_app_count": 2,
        "legacy_user_with_published_apps_count": 1,
        "legacy_user_with_direct_modern_role_count": 2,
        "legacy_direct_role_without_firebase_count": 0,
        "legacy_attribution_only_count": 0,
        "legacy_unreferenced_without_modern_role_count": 1,
        "firebase_identity_count": 3,
        "firebase_role_counts": {"administrator": 1, "none": 1, "publisher": 1},
        "legacy_user_matching_firebase_count": 2,
        "legacy_user_without_firebase_count": 1,
        "firebase_identity_without_legacy_user_count": 1,
        "classification_counts": {
            "matched_role_equivalent": 1,
            "matched_without_modern_role": 1,
            "unmatched_without_direct_modern_role": 1,
        },
        "identity_aggregate_sha256": report["summary"]["identity_aggregate_sha256"],
    }
    by_email = {user["email"].casefold(): user for user in report["users"]}
    assert by_email["publisher@example.test"]["published_app_count"] == 2
    assert by_email["publisher@example.test"]["direct_modern_role"] == "publisher"
    assert by_email["viewer@example.test"]["direct_modern_role"] is None
    assert all(user["migration_action_selected"] is False for user in report["users"])


def test_rejects_broken_identity_relationships() -> None:
    with pytest.raises(ValueError, match="key and email property differ"):
        build_legacy_user_report(
            [entity("RetroStoreUser", "one@example.test", email="two@example.test")],
            [],
            [],
            project="test",
        )

    with pytest.raises(ValueError, match="1 publishers are missing"):
        build_legacy_user_report(
            [],
            [
                entity(
                    "AppStoreItem",
                    "app",
                    listing={"publisherEmail": "missing@example.test"},
                )
            ],
            [],
            project="test",
        )

    with pytest.raises(ValueError, match="Firebase emails are not unique"):
        build_legacy_user_report(
            [],
            [],
            [
                firebase_user("one", "same@example.test"),
                firebase_user("two", "SAME@example.test"),
            ],
            project="test",
        )


def test_report_is_protected_and_contains_no_credentials(tmp_path) -> None:
    report = build_legacy_user_report(
        [entity("RetroStoreUser", "private@example.test", type="NO_ACCOUNT")],
        [],
        [],
        project="test",
    )
    output = tmp_path / "users.json"

    write_protected_report(report, output)

    serialized = output.read_text()
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert json.loads(serialized)["safety"]["contains_credentials"] is False
    assert "private@example.test" in serialized

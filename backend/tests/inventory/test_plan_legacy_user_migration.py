import json

import pytest

from retrostore.inventory.plan_legacy_user_migration import (
    build_legacy_user_migration_plan,
)


def _report() -> dict[str, object]:
    return {
        "schema_version": 1,
        "source": {"project": "trs-80"},
        "safety": {
            "access_mode": "read-only",
            "migration_action_selected": False,
            "contains_credentials": False,
        },
        "summary": {
            "legacy_user_count": 4,
            "published_app_count": 2,
            "firebase_identity_count": 1,
        },
        "users": [
            {
                "email": "admin@example.test",
                "direct_modern_role": "administrator",
                "published_app_count": 1,
                "firebase_matches": [
                    {
                        "uid": "secret-uid",
                        "role": "administrator",
                        "email_verified": True,
                        "disabled": False,
                    }
                ],
            },
            {
                "email": "old-admin@example.test",
                "direct_modern_role": "administrator",
                "published_app_count": 0,
                "firebase_matches": [],
            },
            {
                "email": "publisher@example.test",
                "direct_modern_role": None,
                "published_app_count": 1,
                "firebase_matches": [],
            },
            {
                "email": "historical@example.test",
                "direct_modern_role": None,
                "published_app_count": 0,
                "firebase_matches": [],
            },
        ],
    }


def test_builds_identity_free_no_write_plan() -> None:
    plan = build_legacy_user_migration_plan(_report(), expected_project="trs-80")

    assert plan["evidence"] == {
        "legacy_user_count": 4,
        "published_app_count": 2,
        "firebase_identity_count": 1,
        "proposed_action_counts": {
            "historical_attribution_only": 1,
            "historical_profile_only": 1,
            "manual_invitation_review": 1,
            "retain_existing_firebase_role": 1,
        },
        "manual_review_count": 1,
    }
    assert plan["safety"]["firestore_writes_supported"] is False
    serialized = json.dumps(plan)
    assert "admin@example.test" not in serialized
    assert "secret-uid" not in serialized


def test_requires_matching_project_and_read_only_source() -> None:
    with pytest.raises(ValueError, match="project does not match"):
        build_legacy_user_migration_plan(_report(), expected_project="other")

    report = _report()
    report["safety"]["migration_action_selected"] = True  # type: ignore[index]
    with pytest.raises(ValueError, match="safety boundary"):
        build_legacy_user_migration_plan(report, expected_project="trs-80")


def test_routes_misaligned_existing_identity_to_manual_review() -> None:
    report = _report()
    users = report["users"]  # type: ignore[assignment]
    users[0]["firebase_matches"][0]["role"] = "publisher"  # type: ignore[index]

    plan = build_legacy_user_migration_plan(report, expected_project="trs-80")

    assert plan["evidence"]["proposed_action_counts"]["manual_role_review"] == 1

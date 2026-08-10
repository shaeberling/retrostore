"""Build a no-write, identity-free plan from a protected legacy-user report."""

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from retrostore.inventory.classify_orphaned_blobs import write_protected_report


def build_legacy_user_migration_plan(
    report: Mapping[str, Any], *, expected_project: str
) -> dict[str, Any]:
    """Validate protected evidence and reduce it to non-sensitive action counts."""

    if report.get("schema_version") != 1:
        raise ValueError("Unsupported legacy-user report schema")
    source = report.get("source")
    safety = report.get("safety")
    users = report.get("users")
    if not isinstance(source, Mapping) or not isinstance(safety, Mapping):
        raise ValueError("Legacy-user report metadata is malformed")
    if source.get("project") != expected_project:
        raise ValueError("Legacy-user report project does not match")
    if (
        safety.get("access_mode") != "read-only"
        or safety.get("migration_action_selected") is not False
        or safety.get("contains_credentials") is not False
        or not isinstance(users, list)
    ):
        raise ValueError("Legacy-user report safety boundary is invalid")

    actions: Counter[str] = Counter()
    manual_review_count = 0
    for user in users:
        if not isinstance(user, Mapping):
            raise ValueError("Legacy-user report contains a malformed user")
        action = _proposed_action(user)
        actions[action] += 1
        if action in {"manual_invitation_review", "manual_role_review"}:
            manual_review_count += 1

    summary = report.get("summary")
    if not isinstance(summary, Mapping) or summary.get("legacy_user_count") != len(users):
        raise ValueError("Legacy-user report summary does not match its users")

    encoded = json.dumps(report, separators=(",", ":"), sort_keys=True).encode()
    return {
        "schema_version": 1,
        "operation": "plan_legacy_user_migration",
        "project": expected_project,
        "source_report_sha256": hashlib.sha256(encoded).hexdigest(),
        "safety": {
            "read_only": True,
            "contains_email_addresses": False,
            "contains_firebase_uids": False,
            "contains_credentials": False,
            "firebase_identity_creation_supported": False,
            "firestore_writes_supported": False,
            "role_mutation_supported": False,
            "migration_action_applied": False,
        },
        "evidence": {
            "legacy_user_count": len(users),
            "published_app_count": summary.get("published_app_count"),
            "firebase_identity_count": summary.get("firebase_identity_count"),
            "proposed_action_counts": dict(sorted(actions.items())),
            "manual_review_count": manual_review_count,
        },
        "proposed_policy": {
            "existing_verified_role": "retain_existing_firebase_identity_and_role",
            "unmatched_legacy_admin_or_publisher": (
                "do_not_create_account_automatically; invite only after manual owner review"
            ),
            "published_app_attribution_without_access_role": (
                "retain_as_historical_profile; do not grant authentication access"
            ),
            "unreferenced_profile_without_access_role": (
                "retain_as_disabled_historical_profile; do not grant authentication access"
            ),
            "profile_target": "proposed legacyUserProfiles collection in retrostore database",
            "document_id": "lowercase_email_sha256",
            "approval_required_before_profile_write": True,
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--confirm-project", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.confirm_project != args.project:
        raise ValueError("--confirm-project must exactly match --project")

    source = json.loads(args.source.read_text())
    if not isinstance(source, Mapping):
        raise ValueError("Legacy-user report must be a JSON object")
    plan = build_legacy_user_migration_plan(source, expected_project=args.project)
    write_protected_report(plan, args.output)
    return 0


def _proposed_action(user: Mapping[str, Any]) -> str:
    direct_role = user.get("direct_modern_role")
    published_app_count = user.get("published_app_count")
    matches = user.get("firebase_matches")
    if direct_role is not None and direct_role not in {"administrator", "publisher"}:
        raise ValueError("Legacy-user report has an invalid direct modern role")
    if not isinstance(published_app_count, int) or published_app_count < 0:
        raise ValueError("Legacy-user report has an invalid published-app count")
    if not isinstance(matches, list):
        raise ValueError("Legacy-user report has invalid Firebase matches")
    if len(matches) > 1:
        raise ValueError("Legacy-user report has ambiguous Firebase matches")

    if matches:
        match = matches[0]
        if not isinstance(match, Mapping):
            raise ValueError("Legacy-user report has a malformed Firebase match")
        role = match.get("role")
        verified = match.get("email_verified")
        disabled = match.get("disabled")
        if role == direct_role and verified is True and disabled is False:
            return "retain_existing_firebase_role"
        return "manual_role_review"
    if direct_role is not None:
        return "manual_invitation_review"
    if published_app_count > 0:
        return "historical_attribution_only"
    return "historical_profile_only"


if __name__ == "__main__":
    raise SystemExit(main())

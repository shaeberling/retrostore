# Legacy user migration evidence and proposed policy

Status: Read-only reconciliation complete; profile-write and invitation policy awaiting approval

Last updated: 2026-08-10

## Evidence

The protected read-only reconciliation compared the legacy default-database
`RetroStoreUser` entities, every app publisher reference, all Firebase Auth
identities, and the isolated `retrostore` database role profiles. The detailed
mode-`0600` artifact contains emails and Firebase UIDs and remains gitignored.
The non-sensitive result is:

- 10 legacy records: 3 `ADMIN`, 7 `NO_ACCOUNT`, no `PUBLISHER` or `USER`.
- All 32 apps resolve to 8 of those records as publisher attribution.
- All seven `NO_ACCOUNT` records publish at least one app; they are attribution
  records, not evidence of current login access.
- One legacy administrator matches the only current Firebase identity. Its
  verified Google identity and `administrator` role already agree.
- Two other legacy administrators have no Firebase identity and publish no
  current app.
- There are no Firebase identities outside the legacy set and no role mismatch.

The protected identity aggregate SHA-256 is
`a12090c1281b3743d46c780142c0d0e95e2c5da998a61bd1cbb7fca88ced6a71`.
The identity-free plan is bound to the exact detailed report by SHA-256
`4d37a51871b1a693ffec849798956271943aacb20b1e0b0d253839dbcb31f7c5`.

## Proposed policy

Keep authentication authority and historical attribution separate:

1. Leave the existing verified Firebase administrator and its current role
   unchanged.
2. Preserve all 10 legacy records as historical profiles in a proposed
   `legacyUserProfiles` collection in the named `retrostore` database. Use the
   SHA-256 of the trimmed, case-folded email as the document ID; keep the email,
   names, legacy role, publisher-reference count, source metadata, and migration
   timestamp as document fields. These documents grant no access.
3. Do not automatically create or invite Firebase accounts for the seven
   `NO_ACCOUNT` attribution records.
4. Review the two unmatched historical administrators manually. If either still
   needs access, have that person sign in with a verified Google identity and
   grant a modern role through the audited admin role workflow. Do not infer
   continued access from an old Datastore enum.

This produces seven `historical_attribution_only` actions, two
`manual_invitation_review` actions, and one
`retain_existing_firebase_role` action. It avoids sending invitations to stale
addresses or accidentally converting catalog attribution into administration
authority.

No profile was written, no Firebase identity was created, and no role was
changed. The current planner has no apply path. Adding the profile importer and
running it against the named database requires approval of this policy; any
actual invitation remains a separate explicit operator action.

## Reproduce the read-only evidence

From `backend/`, create the protected reconciliation:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python \
  -m retrostore.inventory.classify_legacy_users \
  --project trs-80 \
  --confirm-project trs-80 \
  --legacy-database '(default)' \
  --admin-database retrostore \
  --auth gcloud \
  --output ../.migration-artifacts/legacy-user-reconciliation.json
```

Then reduce it to a plan containing no email or UID:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python \
  -m retrostore.inventory.plan_legacy_user_migration \
  --source ../.migration-artifacts/legacy-user-reconciliation.json \
  --project trs-80 \
  --confirm-project trs-80 \
  --output ../.migration-artifacts/legacy-user-migration-plan.json
```

Both commands are read-only. Their writers create mode-`0600` files and refuse
to replace existing evidence.

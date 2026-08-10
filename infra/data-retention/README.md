# RetroStore data-retention proposal

This directory records a conservative proposal and deliberately cannot change
Cloud Storage, Firestore, Datastore, App Engine, or local artifacts. Validate it
offline with:

```shell
python3 infra/data-retention/validate.py
```

The read-only bucket inventory was refreshed on 2026-08-10. Hourly sanitized
comparison reports already have a prefix-scoped 90-day lifecycle plus seven-day
soft delete in the private assets bucket. Ephemeral state payloads have their
separate eight-day whole-bucket lifecycle and no soft delete. Neither policy is
changed here. The empty legacy default bucket has no lifecycle rule and is not
selected as a normalized backup target.

Normalized exports and the sensitive identity/orphan reconciliation artifacts
currently exist only in the gitignored operator artifact directory; no cloud
backup location has been approved. The proposal is:

- keep normalized catalog exports and legacy backups for 365 days after final
  App Engine retirement;
- keep the sensitive identity reconciliation for 90 days after identity
  handoff, retaining only its identity-free aggregate afterward;
- keep the Blobstore-key mapping for 365 days after retirement, retaining only
  its key-free aggregate afterward;
- require a separate private backup bucket, manual review after the window, and
  no automatic deletion;
- leave report-queue retention unset until the report workflow itself is
  selected.

These values remain confirmation items. No retention clock starts while App
Engine serves a migrating route, either writer or rollback window remains open,
the final export is not checksum-verified, reconciliation is nonzero, owners
are unconfirmed, or any legal/operational hold exists.

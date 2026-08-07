# RetroStore candidate infrastructure

The replacement services use isolated resources in Google Cloud project
`trs-80`. The legacy `(default)` Datastore-mode database and existing buckets
must remain unchanged throughout the parallel run and rollback window.

## Approved persistence topology

| Resource | Location | Protection and lifecycle | Purpose |
| --- | --- | --- | --- |
| Firestore `retrostore` | `nam5` | Standard, Native mode, delete protection | Durable catalog and administration metadata |
| Firestore `retrostore-state` | `nam5` | Standard, Native mode, `states.expiresAt` TTL | Ephemeral public state-token metadata |
| `gs://trs-80-retrostore-assets` | `US` | Private, uniform access, seven-day soft delete | Durable media, screenshots, and firmware |
| `gs://trs-80-retrostore-state` | `US` | Private, uniform access, soft delete disabled, delete after eight days | Ephemeral serialized state payloads |

The state bucket deliberately disables soft delete. Enabling the default
seven-day soft-delete policy would retain payloads for roughly fifteen days
after combining it with the eight-day object lifecycle. The durable assets
bucket keeps the default recovery window.

The checked-in state lifecycle is in `storage/state-lifecycle.json`. Firestore
TTL and Cloud Storage lifecycle processing are asynchronous and are cleanup
mechanisms only. API correctness must enforce the `expiresAt` timestamp before
reading or allocating state tokens.

No production archive is checked into this directory. Imports must validate the
normalized archive before writing, use immutable checksum-addressed objects,
and emit a reconciliation report into the gitignored `.migration-artifacts/`
directory.

The importer is documented in `../backend/README.md`. It performs no writes
unless `--apply` and an exact project confirmation are both supplied. The first
production-archive dry run on 2026-08-07 targeted these isolated resources and
reconciled 32 apps, 60 media records, 90 screenshots, and 150 objects totaling
12,738,856 bytes. The databases and buckets remain empty pending review of the
implementation and dry-run report.

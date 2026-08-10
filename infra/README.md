# RetroStore candidate infrastructure

The replacement services use isolated resources in Google Cloud project
`trs-80`. The legacy `(default)` Datastore-mode database and existing buckets
must remain unchanged throughout the parallel run and rollback window.

## Approved persistence topology

| Resource | Location | Protection and lifecycle | Purpose |
| --- | --- | --- | --- |
| Firestore `retrostore` | `nam5` | Standard, Native mode, delete protection | Durable catalog and administration metadata |
| Firestore `retrostore-state` | `nam5` | Standard, Native mode, `states.expiresAt` TTL | Ephemeral public state-token metadata |
| `gs://trs-80-retrostore-assets` | `US` | Private, uniform access, seven-day soft delete | Durable catalog media and screenshots |
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
unless `--apply`, an exact project confirmation, and the dedicated keyless
migrator identity are all supplied. On 2026-08-07 the production archive was
imported as content-derived snapshot `catalog-ec07d9d7c8d47c8a46b745fc82b8d7f231e905dc6b6f7e00f4375547cf303de8`.
The first pass created 150 objects totaling 12,738,856 bytes; an immediate retry
created zero and checksum-verified/reused all 150. The state database and bucket
contain four synthetic 34-byte states created by the direct and external
runtime-identity smoke tests; their metadata expires after seven days and their
objects are covered by the eight-day lifecycle. No production state was copied.

The additive, database- and bucket-scoped workload IAM configuration is in
`iam/`. It creates separate migrator, public API, and administration identities
without service-account keys or access to the legacy default database.

The non-routed Cloud Run candidate build and deployment convention is in
`cloud-run/`. Candidate containers use the dedicated runtime identities and
explicit replacement-resource environment variables.

The read-only load-balancer, route-group, monitoring-threshold, and rollback
preparation is in `front-door/`. Its validator is run in CI and deliberately has
no cloud apply path.

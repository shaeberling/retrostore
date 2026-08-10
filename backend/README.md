# RetroStore Python backend

This directory contains the replacement services being built alongside the
authoritative App Engine application:

- `services/api_compat`: the frozen public RetroStore API contract.
- `services/admin`: the server-rendered administration application.
- `retrostore`: shared contract, domain, persistence, and storage code.
- `tests/contract`: executable compatibility scenarios and comparison tests.

Nothing here is deployed to the production `retrostore.org` routes yet.

## Local setup

The CPython 3.14.6 runtime is pinned in `.python-version`, and `uv.lock` pins all
Python dependencies. The current-version and Python 3.14 compatibility audit is
recorded in `DEPENDENCIES.md`.

```shell
cd backend
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv sync --frozen
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run pytest
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run ruff check .
```

Run the fail-closed service skeletons locally from this directory:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run flask --app services.api_compat.app run --port 8080
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run flask --app services.admin.app run --port 8081
```

## Server-rendered admin candidate

The administration service uses Flask/Jinja pages and a Tailwind 4.3.3 asset
compiled at image-build time. It has no browser-facing JSON API for catalog
data. Every admin page verifies a revoked-aware Firebase session cookie and an
administrator or publisher role from the named Firestore database, with the
initial custom claim retained only as a bootstrap fallback until a user profile
exists. Session creation additionally requires a verified email, a sign-in less
than five minutes old, and a matching HTTP-only double-submit CSRF cookie. The
synchronized catalog remains read-only.

Build the local CSS after changing templates or JavaScript:

```shell
npm ci
npm run build:admin-css
```

The deployed candidate is private. Use the official proxy for the first login
and operator review without granting public Cloud Run invocation:

```shell
gcloud run services proxy retrostore-admin-candidate \
  --project trs-80 \
  --region us-central1 \
  --port 8080
```

Then open `http://localhost:8080/admin/login`. Firebase Authentication is
managed as code by the root `firebase.json`; only Google Sign-In is enabled.
The Cloud Run runtime receives a two-permission custom role for session issuance,
revocation checks, and user inspection. It does not receive Firebase user
update, creation, deletion, or provider-configuration access. RetroStore roles
live in the named Firestore database and are re-checked on every protected
request. Publishers cannot access the user inventory or role mutations. Each
role change requires CSRF validation and atomically writes both the user profile
and audit event. Administrators cannot change their own role.

The **Staging** area is the only catalog mutation surface currently enabled. It
uses the top-level `apps`, `authors`, `media`, and `screenshots` working
collections. Materialized `PUBLISHED` baseline records preserve the exact IDs
and metadata of the active immutable snapshot, are visible only to
administrators until explicitly linked to an account, and are read-only in both
the service layer and UI. An administrator can create a copy-on-write metadata
draft for a published app. The editable overlay lives in `appDrafts/{appId}`,
is bound to the exact baseline snapshot and source fingerprint, inherits all
media and screenshot references, and never modifies the source `apps/{appId}`
document. Replacement media and screenshots live in `appDraftMedia` and
`appDraftScreenshots`; removing an inherited asset changes only the overlay,
while removing a draft upload deletes only that draft-owned object. Draft
creation, metadata updates, asset changes, ordering, and discard are optimistic
and audited. Discard cascades through draft-only objects but cannot delete a
published document or object. A stale draft cannot enter a publication
candidate. New `STAGING` records are separate from the versioned
`catalogSnapshots` mirror consumed by the compatibility API, so they cannot
affect public results. Their writes include an atomic `auditEvents` record. App
creation uses a UUID4 form request ID for idempotent retries and enforces
publisher ownership server-side. The staged detail page supports edits guarded
by an optimistic integer revision and deletion guarded by exact-name
confirmation.
It also manages the exact four disk slots plus cassette, command, and BASIC
media, and an explicitly ordered screenshot list. Uploads are size-limited,
checksum-addressed, written to private immutable object paths, and committed to
Firestore atomically with the app revision and audit event. Screenshot content
type is detected from its bytes; SVG is not accepted. Replacements and deletes
remove superseded objects after the metadata transaction. Non-owners and stale
edits are rejected. Deleting an app cascades through its staged assets but
intentionally retains its author document because authors may be shared.

The **Import RPK** workflow accepts one legacy RetroStore Package at a time. Its
first upload is a side-effect-free preview: the complete UTF-8 JSON document,
canonical historical app ID, legacy enums, Base64 payloads, four-disk bound,
asset sizes, and screenshot byte formats are validated before anything can be
written. The operator then re-uploads the exact file; its SHA-256 must match the
preview. Apply preserves the package app ID, refuses to overwrite an existing
staged app, assigns ownership to the signed-in Firebase identity rather than
trusting the publisher claimed by the package, and writes all app/author/asset
metadata plus one `STAGED_RPK_IMPORTED` audit event in a single Firestore
transaction. Newly created immutable objects are removed if any upload or the
metadata transaction fails. The package is limited to 32 MiB encoded and 24 MiB
of decoded assets, with at most four disks and 32 screenshots. Neither upload is
retained as a temporary package object, and the active synchronized catalog
remains read-only.

The read-only lifecycle reconciler checks one exact staged app without emitting
document IDs, object paths, or account identifiers. It verifies linked document
sets, screenshot order, object bytes and SHA-256, superseded-object cleanup,
revision continuity, and the exact audit-event multiset. A mode-`0600` local
checkpoint lets the same command prove cleanup after the app document is gone:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python \
  -m retrostore.admin.reconcile_staging \
  --project trs-80 \
  --database retrostore \
  --bucket trs-80-retrostore-assets \
  --impersonate-service-account retrostore-admin@trs-80.iam.gserviceaccount.com \
  --app-name 'Exact disposable staged app name' \
  --checkpoint /private/path/staging-lifecycle-checkpoint.json \
  --expect-present \
  --expect-media-filename expected.dsk \
  --expect-screenshot-filename expected.png \
  --expect-event-type STAGED_APP_CREATED
```

Repeat with `--no-expect-present`, no expected filenames, and the complete
expected audit-event list after deletion. The command is strictly read-only in
Google Cloud; only its explicitly named local checkpoint is written.

The default API factory reports not-ready until a storage adapter is configured.
Run the explicit representative candidate when exercising the reviewed local
compatibility corpus:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run flask \
  --app 'services.api_compat.app:create_representative_app()' run --port 8080

UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run pytest \
  tests/api_compat/test_representative_contract.py
```

All nine handlers depend on `CompatibilityStorage`, not directly on Flask or a
cloud SDK. `InMemoryCompatibilityStorage` supports deterministic local tests;
the later Firestore/Cloud Storage adapter can replace it without changing
request parsing or response construction. The representative fixture is
explicitly local-only and verifies its captured media payload by size and
SHA-256 before use.

## Public client integration

An opt-in consumer harness runs the published JVM SDK through all nine methods,
compiles the revision- and checksum-pinned RetroStore client from the TRS-80
Kotlin Multiplatform application through its five calls, and compiles the native
C client through all three legacy JSON calls and nanopb decoding. The reviewed
source set also freezes the application's Android, iOS, and browser transports.
The clients talk over real loopback HTTP to the representative Flask candidate;
their synthetic state writes remain in memory.

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python \
  -m retrostore.contract.consumer_clients \
  --trs80-checkout /path/to/TRS-80
```

The reviewed TRS-80 revision, platform transports, source checksums, dependency
pins, and exact coverage split are documented in `consumer-tests/README.md`. CI
checks out only the reviewed client source paths and runs this command
independently of the legacy Java build.

## Protobuf generation

`proto/ApiProtos.proto` is a frozen upstream contract. Do not edit it to change
the legacy API. Regenerate the Python bindings with:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python -m grpc_tools.protoc \
  -I proto \
  --python_out=retrostore/generated \
  proto/ApiProtos.proto
```

The exact upstream revision and checksum are recorded in `proto/UPSTREAM.md`.

## Safe contract capture and comparison

The reviewed corpus has 45 scenarios covering every public method, all three
legacy JSON forms, representative successful catalog/media reads, pagination
and byte-range boundaries, and malformed protobuf for every method. A runtime
safety guard rejects any `uploadState` scenario that could allocate a token.

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python -m retrostore.contract.capture \
  --base-url https://retrostore.org \
  --output /tmp/retrostore-baseline.json

UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python -m retrostore.contract.compare_hosts \
  --reference-url https://retrostore.org \
  --candidate-url https://next.retrostore.org \
  --output /tmp/retrostore-comparison.json
```

The comparator exits nonzero on any transport or semantic difference. Binary
protobuf fields are represented by size and SHA-256 in semantic observations;
response bodies over 64 KiB are hashed but not duplicated as base64. The
reviewed App Engine baseline is versioned under `tests/contract/golden/`.
During parallel-run diagnosis, an exact reviewed difference file can be passed
with `--approvals`. The strict format, expiry/staleness rules, and operational
policy are documented in `retrostore/contract/APPROVED_DIFFERENCES.md`.

For the full read-only data gate, discover every app and media reference from
App Engine and replay the identical generated corpus against a synchronized
candidate:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python \
  -m retrostore.contract.exhaustive \
  --reference-url https://retrostore.org \
  --candidate-url https://next.retrostore.org \
  --output /tmp/retrostore-exhaustive-comparison.json
```

This command cannot generate `uploadState`; it covers full catalog pages,
per-app detail and media responses, media references, and every referenced byte
range. The first App Engine self-comparison matched all 158 observations across
32 apps, 60 media objects, and 6,826,237 media bytes. The report contains
semantic metadata and hashes, not the media binaries.

For a private Cloud Run candidate, add a keyless runtime identity token without
printing or storing it:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python \
  -m retrostore.contract.exhaustive \
  --reference-url https://retrostore.org \
  --candidate-url PRIVATE_CLOUD_RUN_URL \
  --candidate-gcloud-identity-token-service-account \
    retrostore-api@trs-80.iam.gserviceaccount.com \
  --output /tmp/retrostore-cloud-comparison.json
```

Omit `--candidate-audience` when the candidate URL is already the untagged
Cloud Run service URL. Supply it when testing a zero-traffic tag, because Cloud
Run validates the identity token against the untagged service audience.

The guarded capacity harness first captures the same exhaustive production
reference once, then sends only those read-only scenarios concurrently to the
private candidate. It compares every response while measuring latency and
never includes `uploadState`. The command is a no-network dry run unless the
candidate URL is repeated exactly with `--apply`:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python \
  -m retrostore.contract.load_test \
  --candidate-url PRIVATE_CLOUD_RUN_URL \
  --candidate-gcloud-identity-token-service-account \
    retrostore-api@trs-80.iam.gserviceaccount.com \
  --duration-seconds 60 \
  --concurrency 8 \
  --max-requests 2000 \
  --warmup-requests 16 \
  --output /tmp/retrostore-private-load.json \
  --apply \
  --confirm-candidate-url PRIVATE_CLOUD_RUN_URL
```

The report has provisional front-door p95/p99 gates, response counts, and
aggregate latencies but no request/response payloads or identity token. Pair it
with the exact Cloud Run revision's native CPU, memory, instance, concurrency,
request-count, in-container/startup latency, and billable/CPU/memory allocation
metrics. This second command reads only Cloud Monitoring, verifies the
configured project, and also requires all exact target confirmations:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python \
  -m retrostore.contract.cloud_run_metrics \
  --load-report /tmp/retrostore-private-load.json \
  --revision PRIVATE_CLOUD_RUN_REVISION \
  --output /tmp/retrostore-private-load-metrics.json \
  --apply \
  --confirm-project trs-80 \
  --confirm-service retrostore-api-compat-candidate \
  --confirm-revision PRIVATE_CLOUD_RUN_REVISION \
  --require-complete
```

The first real run on 2026-08-10 passed 2,000/2,000 measured requests with zero
transport errors, 5xx responses, or contract differences at 39.15 requests per
second. All per-method latency gates passed. Cloud Monitoring independently
counted exactly 2,016 HTTP 200 requests including warmup, one active instance,
about 1.97% mean CPU utilization, 42.90% mean memory utilization, and 3.94 ms
mean in-container latency over the bounded evidence window. This is useful
headroom evidence for the tested shape, not a final production capacity claim.

After `/downloadapp` was added, the first concurrency-8 run again matched all
2,000 API responses but retained a non-passing provisional latency sample: two
client-observed stalls among only 13 `listAppsNano` requests. Exact-revision
telemetry passed its completeness/resource gate. An independent 2,000-request
confirmation then passed every method gate at 38.08 requests per second with
zero transport errors, 5xx responses, or semantic differences. Both results
are retained; the non-pass is not discarded or treated as a passing sample.

The completed four-step ramp exercised 15,000 measured requests and
1,301,486,720 response bytes at concurrency 8, 12, 16, and 20. Every response
was HTTP 200 with zero transport errors, 5xx responses, or semantic differences.
Concurrency 16 passed all provisional front-door gates at 62.05 requests per
second, although its `listApps` p95 had only about 0.6 ms of margin and is a
measured ceiling rather than an operating target. Concurrency 20 reached 66.56
requests per second but failed the provisional `fetchMediaImageRegion` and
`fetchMediaImages` latency gates. It is retained as the first non-passing
boundary.

The exact-revision native metrics show that boundary was not resource
exhaustion: the concurrency-20 step remained on one instance with CPU p95 at or
below 26%, memory p95 at or below 45%, and in-container p95/p99 latency at or
below 12.1/17.72 ms. It also captured one 950.6 ms startup. The passing
concurrency-16 step used 54.4 billable instance/CPU seconds and 27.2 GiB-seconds
of memory allocation; these are raw cost inputs, not a price estimate. Combine
paired, digest-bound reports without copying their payload-free source detail:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python \
  -m retrostore.contract.capacity_summary \
  --pair /tmp/load-c8.json /tmp/metrics-c8.json \
  --pair /tmp/load-c12.json /tmp/metrics-c12.json \
  --pair /tmp/load-c16.json /tmp/metrics-c16.json \
  --pair /tmp/load-c20.json /tmp/metrics-c20.json \
  --output /tmp/retrostore-capacity-summary.json \
  --require-integrity
```

The metrics collector accepts either the native request-count series or the
native request-latency histogram as complete volume corroboration, records a
warning if they disagree, and requires all resource/allocation series. This is
necessary because the concurrency-20 request-count series reported 4,741 while
its latency histogram independently contained all 5,020 measured-plus-warmup
observations.

Validate the retained hourly evidence and calculate the continuous private
zero-diff clock with:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python \
  -m retrostore.contract.soak_status \
  --thresholds ../infra/front-door/monitoring-thresholds.json \
  --baseline ../infra/front-door/private-soak-baseline.json \
  --output /tmp/retrostore-private-soak-status.json \
  --apply \
  --confirm-project trs-80 \
  --confirm-service retrostore-api-compat-candidate \
  --confirm-revision retrostore-api-compat-candidate-downloads1 \
  --require-current
```

The command impersonates the read-capable migration identity without a key,
downloads only the comparison prefix, pins every download to its object
generation, and verifies its path timestamp, content-derived SHA-256, schema,
URLs, result counts, difference counts, and approval gate. It also proves the
checked-in revision is currently serving 100% of the private candidate. A
failure or gap over 90 minutes restarts or stops the calculated streak. The
summary retains only aggregate evidence and cannot authorize a cutover.

Exercise the deployed write path with one synthetic state only. This guarded
command is a dry run unless `--apply` and an exact URL confirmation are both
present; its report never includes the allocated state token:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python \
  -m retrostore.contract.verify_http_state \
  --candidate-url PRIVATE_CLOUD_RUN_URL \
  --candidate-gcloud-identity-token-service-account \
    retrostore-api@trs-80.iam.gserviceaccount.com \
  --output /tmp/retrostore-cloud-state-http.json \
  --apply \
  --confirm-candidate-url PRIVATE_CLOUD_RUN_URL
```

If the Cloud Run front end itself is under diagnosis, the same runtime identity
can load the real isolated resources into the Flask app in-process and run the
identical read-only corpus without changing service visibility:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python \
  -m retrostore.contract.cloud_exhaustive \
  --reference-url https://retrostore.org \
  --project trs-80 \
  --catalog-database retrostore \
  --assets-bucket trs-80-retrostore-assets \
  --state-database retrostore-state \
  --state-bucket trs-80-retrostore-state \
  --impersonate-service-account \
    retrostore-api@trs-80.iam.gserviceaccount.com \
  --output /tmp/retrostore-isolated-cloud-comparison.json
```

## Normalized catalog mirror

The first Phase 2 persistence boundary is implemented without creating cloud
resources. `CatalogMirror` loads versioned, language-neutral app, media, and
screenshot metadata through an immutable object reader, verifies every object
size and SHA-256, and rejects unsafe paths or broken/cross-app references.
`MirrorCompatibilityStorage` projects that normalized shape back into the
frozen protobuf API, including the exact four-disk/cassette/command/BASIC slot
order and empty placeholders.

The representative normalized mirror passes all 45 reviewed App Engine
observations with zero differences. The read-only Java Objectify exporter emits
a deterministic ZIP containing `manifest.json` and checksum-addressed media and
screenshot objects. It fails on dangling/cross-app references, conflicting
media types, orphaned media, or incomplete Blobstore reads; Blobstore keys are
not serialized. The Python archive loader independently verifies paths, object
digests, counts, byte totals, and the aggregate digest. Validate a downloaded
production export and print only aggregate evidence with:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python \
  -m retrostore.mirror.verify_archive \
  /path/to/retrostore-catalog-export.zip
```

Run an explicitly archive-backed local candidate, then compare its complete
catalog and media contents with App Engine:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run flask \
  --app 'services.api_compat.app:create_archive_app("/path/to/retrostore-catalog-export.zip")' \
  run --port 8080

UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python \
  -m retrostore.contract.exhaustive \
  --reference-url https://retrostore.org \
  --candidate-url http://127.0.0.1:8080 \
  --output /tmp/retrostore-archive-comparison.json
```

The format and its current scope are in `retrostore/mirror/FORMAT.md`. The
temporary App Engine export route is available only on specially named
`migration-export-*` default-service versions and additionally enforces the
RetroStore admin role and explicit confirmation. The export implementation does
not read or mutate Firebase. The persistence boundary described below is the
only path that can copy a validated archive into the isolated replacement
resources.

## Controlled cloud catalog import

The cloud importer validates the complete archive and target names before it
constructs cloud clients. It defaults to a zero-write dry run:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python \
  -m retrostore.mirror.import_catalog \
  /path/to/retrostore-catalog-export.zip \
  --project trs-80 \
  --database retrostore \
  --bucket trs-80-retrostore-assets \
  --output /tmp/retrostore-catalog-import-dry-run.json
```

An apply additionally requires both `--apply` and an exact
`--confirm-project trs-80`, plus impersonation of the dedicated keyless
`retrostore-migrator` identity:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python \
  -m retrostore.mirror.import_catalog \
  /path/to/retrostore-catalog-export.zip \
  --project trs-80 \
  --database retrostore \
  --bucket trs-80-retrostore-assets \
  --output /tmp/retrostore-catalog-import.json \
  --apply \
  --confirm-project trs-80 \
  --impersonate-service-account \
    retrostore-migrator@trs-80.iam.gserviceaccount.com
```

The operator receives a short-lived impersonated access token from `gcloud`;
no service-account key is created or written to disk.

Objects are uploaded with a generation-zero precondition and independently
verified when an immutable path already exists. Firestore metadata is written
under a content-derived `catalogSnapshots/{snapshotId}` document. Only after
all documents reconcile does one atomic batch mark the snapshot ready and move
`catalogControl/active` to it. Failed or interrupted imports cannot expose a
partially written snapshot, and retrying the same archive reuses verified
objects and the same snapshot ID.

The bootstrap importer is intentionally not the recurring synchronization
command because its successful apply activates the imported snapshot. After the
initial bootstrap, validate every new full legacy export with the separate
stage-only refresh boundary:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python \
  -m retrostore.mirror.stage_catalog_refresh \
  /path/to/new-retrostore-catalog-export.zip \
  --baseline-archive /path/to/previous-retrostore-catalog-export.zip \
  --project trs-80 \
  --database retrostore \
  --bucket trs-80-retrostore-assets \
  --output /tmp/retrostore-catalog-refresh-dry-run.json
```

The dry run constructs no cloud clients. It reports only source/snapshot
digests, aggregate counts, and added/changed/removed record IDs; it does not
copy catalog field values into the operational report. A stage apply requires
the exact active snapshot ID and manifest digest in addition to the normal
project and migrator confirmations:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python \
  -m retrostore.mirror.stage_catalog_refresh \
  /path/to/new-retrostore-catalog-export.zip \
  --project trs-80 \
  --database retrostore \
  --bucket trs-80-retrostore-assets \
  --output /tmp/retrostore-catalog-refresh-stage.json \
  --apply-stage \
  --confirm-project trs-80 \
  --impersonate-service-account \
    retrostore-migrator@trs-80.iam.gserviceaccount.com \
  --expected-active-snapshot-id catalog-EXPECTED_SHA256 \
  --expected-active-manifest-sha256 EXPECTED_SHA256
```

This command can create/reuse immutable objects and stage a reconciled snapshot,
but it has no activation option. It reloads the active mirror after staging and
fails unless the complete active snapshot is unchanged. Activation remains a
separate guarded, audited compare-and-swap operation.

## Exact snapshot export and legacy reverse planning

One exact staged or ready cloud snapshot can be read back through the migrator
identity and written as a create-only normalized archive. The command requires
both the content-derived snapshot ID and manifest digest, reloads every object
with checksum verification, and round-trips the completed archive before
reporting success:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python \
  -m retrostore.mirror.export_catalog_snapshot \
  --project trs-80 \
  --database retrostore \
  --bucket trs-80-retrostore-assets \
  --snapshot-id catalog-CANDIDATE_SHA256 \
  --manifest-sha256 CANDIDATE_SHA256 \
  --output-archive /secure/path/candidate.zip \
  --output-report /tmp/retrostore-candidate-export.json \
  --impersonate-service-account \
    retrostore-migrator@trs-80.iam.gserviceaccount.com
```

Compare that immutable candidate with the last exact legacy export to produce a
deterministic reverse-sync plan:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python \
  -m retrostore.mirror.plan_legacy_reverse_sync \
  --baseline-archive /secure/path/legacy-baseline.zip \
  --candidate-archive /secure/path/candidate.zip \
  --output /tmp/retrostore-legacy-reverse-plan.json
```

The plan includes archive/snapshot digests, ID-only app/media/screenshot/Search
operations, numeric legacy ID allocations and absence checks, Blobstore work,
ordered writer-freeze/reconciliation phases, and a digest of the plan itself.
It contains no catalog field values, publisher identities, or binary objects.
This boundary is deliberately read-only and reports `apply_available=false`;
the App Engine importer must not be enabled until its ID allocation, screenshot
Blobstore creation, Search updates, exact baseline precondition, and complete
post-import export/API reconciliation are implemented and tested together.

The legacy Java tree also contains a disabled
`NormalizedCatalogArchiveValidator`. It independently validates both complete
archives, their enums, positional slots, references, object bytes, and aggregate,
then reports only added/changed/removed counts and the counts of numeric author
and media allocations, absence checks, and screenshot Blobstore writes. It has
no servlet registration, entity mapper, ID allocator, Blobstore/Search adapter,
Objectify call, or apply method. The candidate's catalog values and IDs are not
returned in its preflight report.

## Controlled working-catalog materialization

The initial admin working set is derived deterministically from the same
validated archive and its active immutable snapshot. It preserves historical
application, author, media, and screenshot IDs, exact media slots and screenshot
order, timestamps, checksums, object paths, legacy screenshot URLs, and source
publisher email. It deliberately assigns no Firebase publisher ownership.
Source fingerprints on every document and a content-derived
`catalogWorkingControl/current` record make the operation independently
reconcilable.

The command is a zero-write dry run by default:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python \
  -m retrostore.admin.materialize_working_catalog \
  /path/to/retrostore-catalog-export.zip \
  --project trs-80 \
  --database retrostore \
  --bucket trs-80-retrostore-assets \
  --output /tmp/retrostore-working-catalog-dry-run.json
```

Apply requires the exact project confirmation and dedicated keyless migrator:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python \
  -m retrostore.admin.materialize_working_catalog \
  /path/to/retrostore-catalog-export.zip \
  --project trs-80 \
  --database retrostore \
  --bucket trs-80-retrostore-assets \
  --output /tmp/retrostore-working-catalog.json \
  --apply \
  --confirm-project trs-80 \
  --impersonate-service-account \
    retrostore-migrator@trs-80.iam.gserviceaccount.com
```

Before writing, apply reloads the active cloud snapshot through the migrator
identity and verifies that it exactly matches the archive, including every
object checksum. All source documents, the control record, and one sanitized
`CATALOG_WORKING_SET_MATERIALIZED` audit event are then created in one Firestore
batch. Any pre-existing source ID is treated as a conflict unless the matching
control record already proves an idempotent completed operation. The command
does not upload, replace, or delete objects and never moves
`catalogControl/active`.

## Stage-only publication candidates

The publication builder reads the immutable source portion of the live working
collections, reconciles its control record and single audit event, validates
every source fingerprint, and overlays isolated `STAGING` apps and
copy-on-write `DRAFT` records. It validates app ownership, timestamps, author
references, media slot types, screenshot ordering, object sizes, and SHA-256
before deriving a content-addressed immutable snapshot. With no pending changes
it must rebuild the exact active snapshot; with pending changes it must derive a
different candidate. The command can stage that candidate but cannot activate
it.

Its default mode is fully read-only but still requires the dedicated migrator
identity so no ambient credential can select a different database:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python \
  -m retrostore.admin.stage_working_catalog \
  --project trs-80 \
  --database retrostore \
  --bucket trs-80-retrostore-assets \
  --output /tmp/retrostore-working-stage-dry-run.json \
  --impersonate-service-account \
    retrostore-migrator@trs-80.iam.gserviceaccount.com
```

`--apply --confirm-project trs-80` additionally invokes only the snapshot
store's stage boundary. A ready snapshot is never accepted merely by root
identity: all nested app, media, and screenshot documents are reloaded and
hashed. The command refuses a working baseline that is not based on the exact
active snapshot, never uploads objects, and cannot move `catalogControl/active`.

## Private pinned preview and guarded activation

The compatibility API can be pinned to one explicit `STAGED` or `READY`
snapshot by setting both `RETROSTORE_CATALOG_SNAPSHOT_ID` and
`RETROSTORE_CATALOG_SNAPSHOT_MANIFEST_SHA256`. This is intended only for a
separate private preview revision. Startup fails if either value is missing or
the complete nested manifest does not hash to the supplied digest. The normal
candidate remains unpinned and continues to load `catalogControl/active`.

New screenshots without a legacy App Engine serving URL use an absolute,
configurable `RETROSTORE_PUBLIC_ORIGIN` plus the short `/s/{id}` path. The short
form fits the reviewed native client's URL-size expectation, while an absolute
URL works with the Android and iOS platform clients. That route reads the
already checksum-verified private object at startup and serves it with a strong
ETag, detected image content type, public CORS, `nosniff`, and immutable
one-year caching.
Existing published screenshot URL strings remain byte-for-byte unchanged.

Activation and rollback are deliberately separate from staging. The operator
command is read-only by default and requires the candidate and expected active
snapshot IDs plus both exact manifest digests:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python \
  -m retrostore.admin.activate_catalog_snapshot \
  --project trs-80 \
  --database retrostore \
  --bucket trs-80-retrostore-assets \
  --operation activate \
  --candidate-snapshot-id CANDIDATE_SNAPSHOT_ID \
  --candidate-manifest-sha256 CANDIDATE_MANIFEST_SHA256 \
  --expected-active-snapshot-id ACTIVE_SNAPSHOT_ID \
  --expected-active-manifest-sha256 ACTIVE_MANIFEST_SHA256 \
  --actor OPERATOR_IDENTITY \
  --output /tmp/retrostore-catalog-activation-dry-run.json \
  --impersonate-service-account \
    retrostore-migrator@trs-80.iam.gserviceaccount.com
```

Apply additionally requires `--apply` and four literal confirmations:
`--confirm-project`, `--confirm-operation`,
`--confirm-candidate-snapshot-id`, and
`--confirm-expected-active-snapshot-id`. A Firestore transaction then re-reads
and re-hashes both complete snapshots, compare-and-swaps the exact active
pointer, marks the candidate `READY`, and creates an audit event. A rollback
uses `--operation rollback` through the same primitive and accepts only an
already-`READY` snapshot. This command must not be applied until the private
preview, compatibility, monitoring, ownership, and go/no-go gates are complete.

## Controlled cloud state smoke test

The state adapter stores normalized protobuf bytes in the isolated private state
bucket and transactionally claims metadata in the `retrostore-state` database.
The command is a zero-write dry run unless the exact project and API runtime
identity are confirmed:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python \
  -m retrostore.api_compat.verify_cloud_state \
  --project trs-80 \
  --database retrostore-state \
  --bucket trs-80-retrostore-state \
  --output /tmp/retrostore-state-smoke.json \
  --apply \
  --confirm-project trs-80 \
  --impersonate-service-account \
    retrostore-api@trs-80.iam.gserviceaccount.com
```

The fixture contains no production state. A successful run proves an immutable
object write, transactional legacy-range token claim, checksum-verified
read-back, and exact protobuf round trip. The test record expires after seven
days and the bucket lifecycle deletes its object after eight days.

## Live state export and rollback planning

The state route group cannot be rolled back safely unless every still-live state
created after a future writer handoff can be restored under its exact 100-999
token. Export all logically live records through the private API runtime
identity into a create-only mode-`0600` archive:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python \
  -m retrostore.api_compat.export_state_snapshot \
  --project trs-80 \
  --database retrostore-state \
  --bucket trs-80-retrostore-state \
  --output-archive /secure/path/live-states.zip \
  --output-report /tmp/retrostore-live-states.json \
  --impersonate-service-account \
    retrostore-api@trs-80.iam.gserviceaccount.com
```

The exporter validates every Firestore token document, Cloud Storage generation,
size, SHA-256, timestamp window, and `SystemState` protobuf. The archive contains
the exact tokens and memory data and must remain private; the console/report
contains only counts, byte totals, expiry bounds, and aggregate digests.

Build a token-free rollback plan with:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python \
  -m retrostore.api_compat.plan_legacy_state_reverse_sync \
  --state-archive /secure/path/live-states.zip \
  --output /tmp/retrostore-state-reverse-plan.json
```

The plan requires freezing replacement writes, rejecting every legacy token
collision unless its full state is identical, preserving the original token and
creation timestamp, verifying full/metadata-only/region downloads, switching
all three state RPC routes atomically, and restoring exactly one writer. It has
no apply path. No Blobstore or Search operation is involved because legacy
states are Objectify entities with embedded memory bytes.

The legacy Java tree contains a matching `NormalizedStateArchiveValidator`.
It independently enforces the archive limits, live windows, paths, protobufs,
checksums, and aggregate, then maps each record to a fresh in-memory Objectify
`SystemState` entity. It has no servlet registration, Objectify call, mutation
method, or apply command. A pure read-only preflight classifies absent,
byte-for-byte-equivalent, and expired legacy token collisions and rejects a
different live state without putting its token in an error. This closes the
cross-language format/conversion and collision-policy unit gates, not the frozen
production preflight, persistence, RPC reconciliation, or writer-handoff gates.

## Read-only production inventory

The inventory command reads the legacy Datastore-mode database and emits a
sanitized report containing only aggregate counts, schema shapes, sizes,
checksums, and referential-integrity findings. It does not include entity keys,
property values, user details, or binary contents, and its source adapter has no
mutation methods.

Use Application Default Credentials in automation:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python -m retrostore.inventory.cli \
  --project trs-80 \
  --output /tmp/retrostore-inventory.json
```

For an operator session already authenticated with gcloud, add `--auth gcloud`.
Add `--fail-on-integrity-errors` in CI or reconciliation jobs once any reviewed
legacy exceptions have been classified. Blobstore rows provide metadata and
MD5 values only. The App Engine-side bundled-services operation independently
hashed all 98 production objects twice and reconciled all 32 live Search
documents with their source app entities. The normalized reports matched; see
`docs/appengine-bundled-services-inventory.md` for the retained aggregate
evidence and controlled-deployment record.

The aggregate command deliberately cannot classify orphan identifiers. Use the
separate production-read classifier only with an explicit project confirmation,
the retained sanitized byte-verification report, and the retained normalized
catalog archive:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python \
  -m retrostore.inventory.classify_orphaned_blobs \
  --project trs-80 \
  --confirm-project trs-80 \
  --auth gcloud \
  --bundled-services-report ../.migration-artifacts/bundled-services-inventory-20260806-150441.json \
  --catalog-archive ../.migration-artifacts/retrostore-catalog-export.zip \
  --output ../.migration-artifacts/orphaned-blob-preservation.json
```

The output is create-only with mode `0600`, contains Blobstore keys and their
mapping to normalized screenshot IDs, and must stay in the gitignored restricted
artifact directory. The command has no mutation adapter. It fails on missing or
duplicate metadata, unverified content evidence, or an archive that does not
contain byte-identical preservation sources.

Reconcile the sensitive legacy user records against app attribution, Firebase
Auth, and the isolated admin role store without creating accounts or roles:

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

The mode-`0600` output contains email addresses and Firebase UIDs. Reduce it to
an identity-free, no-write policy plan with:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python \
  -m retrostore.inventory.plan_legacy_user_migration \
  --source ../.migration-artifacts/legacy-user-reconciliation.json \
  --project trs-80 \
  --confirm-project trs-80 \
  --output ../.migration-artifacts/legacy-user-migration-plan.json
```

Neither command has an identity-creation, role-mutation, or Firestore-write
path. The proposed policy and approval boundary are documented in
`docs/legacy-user-migration.md`.

The compatibility service also reconstructs the public legacy
`/downloadapp?appId=...&type=...` route from the normalized mirror. Compare all
current app ZIPs, every current per-app extension, and malformed requests with:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python \
  -m retrostore.contract.legacy_downloads \
  --archive ../.migration-artifacts/retrostore-catalog-export.zip \
  --reference-url https://retrostore.org \
  --output ../.migration-artifacts/legacy-download-comparison.json
```

The comparison checks exact status and relevant response headers. Direct media
bytes are SHA-256 compared. ZIPs are compared by filename digest, uncompressed
size, and content SHA-256; generated timestamp/compressor envelope differences
are ignored because App Engine rebuilds that envelope on each request. Reports
contain no app IDs, filenames, or media bytes.

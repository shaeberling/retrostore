# RetroStore Modernization and App Engine Migration Plan

Status: In progress

Last updated: 2026-08-07

## Implementation status

Phase 0 and Phase 1 have started on branch `codex/cloud-run-migration-plan`.
Completed foundation work:

- The local gcloud project and repository Firebase default are set to `trs-80`.
- The API 0.2.13 protobuf schema is vendored with an exact upstream revision,
  upstream checksum, normalized vendored checksum, and generated Python code.
- A Python 3.14.6 `uv` workspace and lockfile now define the shared backend and
  the independently deployable Flask API/admin service skeletons.
- Every direct and transitive Python dependency has been audited against current
  stable PyPI metadata. The 55-record locked graph has no outdated or
  inconsistent packages, and its Python 3.14 compatibility evidence is recorded
  in `backend/DEPENDENCIES.md`.
- A separate GitHub Actions workflow installs the frozen lockfile and runs the
  backend linter and tests on pushes and pull requests to `master`.
- A machine-readable registry freezes all nine API methods, both raw-byte
  responses, all three legacy JSON forms, and the state-writing method.
- A mutation-safe contract harness, binary-aware semantic protobuf normalizer,
  two-host comparator, and reviewed 45-scenario App Engine golden baseline are
  in place. Two independent complete captures matched with zero differences.
- The read-only production infrastructure inventory is recorded in
  `docs/current-system-inventory.md`: App Engine deployment and domains,
  Datastore kind counts, Blobstore size, buckets, DNS, IAM, and the absence of
  Cloud Run and load-balancer resources are now established.
- A strict read-only Python inventory/reconciliation command scans legacy
  Datastore, fingerprints non-user records and binary fields, records schema
  shapes, applies the seven-day state rule, and validates app, author, user,
  media, and Blobstore references without emitting production identifiers or
  values. Its first production run found no broken references and eight
  unreferenced Blobstore objects to preserve and investigate.
- The legacy Java build is reproducible again: Java 21.0.12+8 builds Java 11
  bytecode for the supported App Engine Java 25 runtime in EE 8 compatibility
  mode, with checksum-pinned Gradle 8.14.5, the current App Engine plugin and
  stable SDK, immutable dependencies, full dependency verification, and CI.
- An admin-only, no-store App Engine operation now streams and hashes all
  Blobstore content and compares the live Search index with current app entities
  using sanitized aggregate output. Twelve focused Java tests cover its hashing,
  reconciliation, Java 25 compatibility, access control, failure handling, and
  non-disclosure rules.
- Two authenticated production reports from non-promoted Java 25 version
  `migration-inventory-20260806-145211` matched after excluding `generated_at`.
  Their normalized SHA-256 is
  `7ba290376c6641c511c7cd58b4b1a7c745d7ba2780d425903de69da84de4fb71`.
  All 98 Blobstore objects were content-verified, and all 32 Search documents
  exactly matched their Datastore-derived expectations. The three temporary
  inventory versions were deleted after validation; production routing remained
  100% on `20230819t145020` throughout.
- The local Flask compatibility candidate now implements all nine public methods
  behind a cloud-independent `CompatibilityStorage` boundary. Its explicit
  representative in-memory adapter passes all 45 reviewed App Engine scenarios
  with zero transport or semantic differences. Valid state round-trip, memory
  exclusion, and overlapping-region behavior also have isolated local coverage;
  the default deployable factory remains fail-closed without a real adapter.
- A separate checksum-verified consumer build now runs the published JVM SDK
  0.2.13 through all nine methods, compiles the reviewed TRS-80 Kotlin
  Multiplatform client through its five production calls, and compiles the
  embedded C client through all three legacy JSON calls and nanopb decoding.
  All pass over real loopback HTTP against the Flask candidate, including
  isolated state writes.
- A dynamic read-only comparator now discovers every public app and media
  reference from the authoritative host, replays the same requests against a
  candidate, hashes binary fields, and retrieves every referenced media byte.
  Its first two independent App Engine captures matched across all 158
  scenarios: 32 apps, 60 non-empty media objects, and 6,826,237 media bytes.
- The isolated state suite now covers the exact legacy validation boundaries,
  declared-length normalization, zero-filled gaps, overlap precedence,
  concurrent token allocation, the 100–999 token range, wrap/exhaustion, and
  persistence clone isolation. Matching Java/Python fixtures prove that the
  legacy contract accepts a 2,000,028-byte valid state, beyond Firestore's 1 MiB
  document limit. The complete Python suite has 75 passing tests.
- Comparator reports now include a strict approved-difference gate. An approval
  pins one scenario field's exact reference/candidate fingerprint and requires
  a reason, named owner, and expiry. Changed, expired, duplicate, or unused
  approvals fail instead of masking drift.
- A versioned normalized catalog mirror now separates app/media/screenshot
  metadata from immutable object bytes, verifies size and SHA-256, rejects
  broken or cross-app references, and reconstructs all ordered legacy media
  slots. Its compatibility adapter matches all 45 reviewed App Engine
  observations with zero differences without accessing Firebase.
- A read-only Java Objectify exporter now emits the normalized catalog shard as
  a deterministic ZIP with checksum-addressed media/screenshots, a supplied
  high-water mark, and reconciliation counts and digests. It fails on dangling,
  cross-app, conflicting-type, orphaned, or incomplete binary reads; its Python
  archive loader independently verifies the artifact before use.
- A controlled catalog-export route is implemented and tested. It is hidden
  unless the default-service App Engine version starts with
  `migration-export-`, then requires a RetroStore admin session, GET, and an
  explicit confirmation value. Its ZIP response is private, non-cacheable, and
  has no public CORS header. Java 25 version
  `migration-export-20260807-1312` was deployed without promotion on 2026-08-07;
  an unauthenticated request returned HTTP 403 while production traffic
  remained 100% on `20230819t145020`. The authenticated export passed the
  independent Python loader with 32 apps, 60 media records, 90 screenshots,
  and 150 objects totaling 12,738,856 bytes. The 8,418,142-byte ZIP has SHA-256
  `3bf584091e59bd5200bc36c8178aa9923148e8999eae0238f5577a5ade4fcefa` and is
  retained only in `.migration-artifacts/`. The temporary version was deleted
  after validation, and production traffic remained unchanged.
- The local Flask candidate now has an explicit archive-backed factory while
  its default factory remains fail-closed. The full synchronized comparison
  replayed all 158 read-only scenarios against `retrostore.org` and this
  production archive: all 32 apps, 60 media objects, 60 byte-range reads, and
  6,826,237 media bytes matched with zero differences and no approvals.

Open foundation work:

- The verified normalized archive now needs to be imported into isolated
  Firestore/Cloud Storage resources and served through the production adapter.
  Database and bucket location, names, retention, and lifecycle policy remain
  deliberate operator decisions; the local archive factory stays explicit and
  the default deployable factory remains fail-closed.
- The `native-client-library` Arduino tree is an unfinished prototype: it sends
  a bodyless GET, ignores its configurable host, and has no media
  implementation. It needs an explicit retire-or-modernize decision rather than
  being classified as a working contract consumer.
- No production routing has changed, and no temporary migration version remains.

## Executive summary

RetroStore should move away from its monolithic App Engine application using a
compatibility-first, incremental migration. The agreed target is:

- A dedicated Python/Flask Cloud Run service for the existing public RetroStore
  API.
- A separate Python/Flask Cloud Run service that serves the admin HTML and owns
  all administrative operations.
- A server-rendered admin interface using Jinja, compiled Tailwind CSS, and
  optional htmx enhancements rather than a single-page application.
- Firebase Authentication for admin and publisher identities, exchanged for
  secure server-side session cookies.
- A new named Firestore Native database for normalized catalog metadata.
- A separate named Firestore Native database for ephemeral system states.
- Private Cloud Storage for Firebase buckets for media images, screenshots,
  firmware, and migration artifacts.
- A one-time normalized export from Objectify into the new Firestore and Storage
  model, leaving the existing Datastore-mode database untouched for rollback.
- A mandatory parallel-run period in which App Engine remains authoritative and
  the new services are continuously synchronized and compared against it.
- A route-by-route production cutover only after explicit compatibility,
  operational, and rollback gates have passed.

The public API remains the highest-risk part of the migration. Its current
transport and semantic behavior must be documented and protected by consumer and
golden-response tests before production traffic moves.

Firebase is the persistence platform, not the application trust boundary. The
browser uses Firebase directly for authentication only. The Flask services use
their Cloud Run identities to access Firestore and Cloud Storage and enforce all
authorization and business rules server-side.

## Recorded architecture decisions

- Use Python and Flask for both new backend services.
- Use Gunicorn as the production WSGI server on Cloud Run.
- Do not introduce FastAPI unless a substantial new JSON/OpenAPI API becomes a
  product requirement.
- Do not introduce Go solely for performance; the compatibility tests leave a
  future rewrite possible if it becomes desirable.
- Keep the compatibility API and admin application as separate deployments.
- Serve the admin UI and its backend from one Flask service; do not create a
  separate browser-facing admin JSON API without another consumer.
- Use server-rendered Jinja templates and ordinary HTML forms.
- Compile Tailwind into a static CSS asset with no CSS runtime dependency.
- Add htmx or small vanilla JavaScript enhancements only where they materially
  improve an interaction.
- Create new named Firestore Native databases rather than converting or writing
  new schema into the existing Objectify/Datastore database.
- Keep binary data in Cloud Storage, not Firestore.
- Keep Firestore and Storage inaccessible to browser clients by default.
- Keep App Engine authoritative throughout implementation and the comparison
  soak; the existing production URLs are the last thing to move.
- Expose the candidate services on separate hostnames and do not allow both
  admin applications to write production catalog data concurrently.
- Put a global external Application Load Balancer in front of App Engine and
  Cloud Run. Initially route production traffic 100% to App Engine, then move
  verified route groups through URL-map changes rather than further DNS changes.
- Require zero unexplained contract differences over the complete comparison
  corpus and the agreed soak period before a public API route can move.

## Goals

- Remove the runtime dependency on App Engine and its legacy bundled services.
- Preserve the public API contract for existing Android, iOS, web, JVM, C, and
  embedded clients.
- Modernize the admin interface and authentication model without creating a
  complex frontend application.
- Move structured data to a language-neutral Firestore schema.
- Move binary data out of Datastore and Blobstore into Cloud Storage.
- Separate the stable public compatibility API from the faster-moving admin
  application.
- Make deployments testable, observable, and safely reversible.
- Use least-privilege identities for the public API and admin services.
- Run the legacy and replacement stacks in parallel long enough to compare their
  behavior over the complete data corpus and representative live conditions.
- Make every production route change quickly reversible without another DNS
  migration.

## Non-goals

- Redesigning or removing the existing `/api/*` contract.
- Requiring existing public clients to authenticate.
- Changing existing app IDs, media order, filenames, or protobuf field numbers.
- Building a public direct-to-Firestore or direct-to-Storage client.
- Building a React, Next.js, or other SPA-based admin interface.
- Migrating every subsystem and every stored entity in a single release.
- Deleting or converting the existing Datastore-mode database during the
  migration or rollback window.
- Sending the same real state write to both stacks or otherwise duplicating
  user-visible side effects during comparison.
- Operating the legacy and new admin applications as simultaneous production
  writers.
- Pointing the production hostname directly at Cloud Run before the load
  balancer and App Engine-only routing have been tested in production.

## Current architecture

Production traffic currently runs a Java 11 App Engine WAR. The source is now
configured for Java 25 in EE 8 compatibility mode while retaining Java 11
bytecode and the existing `javax.servlet` application contract. A catch-all
servlet dispatches the public website, public API, admin application, uploads,
screenshots, reporting, firmware/card endpoints, and static resources.

The application currently depends on:

- App Engine Datastore through Objectify.
- Blobstore for screenshots and upload handling.
- The App Engine Images service for serving image URLs.
- The App Engine Search service for catalog search.
- Memcache for state-token allocation, image URL caching, and resource caching.
- The App Engine Users service for admin authentication.
- The App Engine Mail service for reports.
- A cron ping that keeps the application warm.

Media images are stored as raw byte arrays in Datastore entities. App records
contain nested Objectify POJOs, enums, sets, arrays, and Blobstore keys. These
representations must be normalized during migration rather than becoming the
permanent Python persistence contract.

The admin interface uses Polymer 2 and Bower-era dependencies. It manages apps,
users, media images, and screenshots through internal `/rpc` calls and Blobstore
upload URLs.

## Public compatibility contract

The public API currently exposes nine methods:

| Group | Endpoint |
| --- | --- |
| Catalog | `/api/getApp` |
| Catalog | `/api/listApps` |
| Catalog | `/api/listAppsNano` |
| Media | `/api/fetchMediaImages` |
| Media | `/api/fetchMediaImageRefs` |
| Media | `/api/fetchMediaImageRegion` |
| State | `/api/uploadState` |
| State | `/api/downloadState` |
| State | `/api/downloadStateMemoryRegion` |

The canonical protobuf schema is API version 0.2.13 in the
[RetroStore JVM SDK](https://github.com/shaeberling/retrostore-jvm-sdk/blob/main/src/main/proto/org/retrostore/client/common/proto/ApiProtos.proto).

Compatibility includes more than message field definitions:

- Clients POST raw protobuf request bodies without requiring a `Content-Type`.
- `getApp`, `listApps`, and `fetchMediaImages` also accept legacy JSON request
  bodies.
- The server returns protobuf as `application/octet-stream`.
- Most semantic errors use HTTP 200 with `success=false` in the protobuf body.
- Unknown API methods use HTTP 400 and a plain-text response.
- Media-region and state-memory-region calls return raw bytes rather than a
  protobuf envelope.
- `fetchMediaImages` emits media in a fixed order and includes empty placeholder
  messages for unpopulated slots.
- Catalog ordering, filtering, and pagination behavior are observable client
  behavior and must remain stable.
- The API is public and currently sends `Access-Control-Allow-Origin: *`.
- The browser client relies on a CORS simple request and deliberately omits a
  content type to avoid a preflight request.
- The service currently responds directly over both HTTP and HTTPS. The embedded
  C implementation uses plain HTTP and must either remain supported or be
  migrated and proven safe before cutover.

### Known consumers

The actively maintained
[TRS-80 Kotlin Multiplatform application](https://github.com/apuder/TRS-80)
uses Wire-generated protobuf messages and currently calls:

- `getApp`
- `listApps`
- `fetchMediaImages`
- `uploadState`
- `downloadState`

The same repository also contains an
[embedded C client](https://github.com/apuder/TRS-80/blob/master/app/src/main/c/retrostore/backend.cpp)
that sends legacy JSON requests to `getApp`, `listApps`, and
`fetchMediaImages`, then parses protobuf responses.

Other SDKs and deployed clients may use all nine methods. Unused methods must not
be removed without a separately versioned API and an explicit deprecation plan.

## Target architecture

### Trust and data flow

```text
Browser
  └── Firebase Authentication
          │ secure session-cookie exchange
          ▼
Flask admin ──► Firestore catalog metadata
            └─► Cloud Storage objects

RetroStore clients
          ▼
Flask compatibility API ──► Firestore catalog metadata
                         ├─► Cloud Storage media
                         ├─► Firestore state-token database
                         └─► Cloud Storage state payloads
```

### Python repository layout

The two services should share domain and persistence adapters while retaining
separate entry points and containers:

```text
backend/
├── pyproject.toml
├── proto/
│   └── ApiProtos.proto
├── retrostore/
│   ├── auth/
│   ├── domain/
│   ├── generated/
│   ├── persistence/
│   └── storage/
├── services/
│   ├── api_compat/
│   │   ├── app.py
│   │   └── Dockerfile
│   └── admin/
│       ├── app.py
│       ├── templates/
│       ├── static/
│       └── Dockerfile
└── tests/
    ├── admin/
    ├── contract/
    └── persistence/
```

Use a locked `pyproject.toml` dependency set and a pinned Python runtime. The
Flask application-factory pattern and Blueprints should separate apps, users,
firmware, authentication, and other admin concerns.

### Request routing

`retrostore.org` remains the stable public hostname. The eventual routing is:

| Path or surface | Target |
| --- | --- |
| Public static website | Dedicated Cloud Storage backend bucket, optionally CDN-cached |
| `/api/*` | `retrostore-api-compat` Flask service on Cloud Run |
| `/admin/*` | `retrostore-admin` Flask service on Cloud Run |
| `/assets/screenshots/*` | Stable RetroStore asset handler, optionally CDN-cached |
| Legacy public dynamic routes | Compatibility service until migrated |

Use a global external Application Load Balancer as the production front door.
Serverless network endpoint groups can target both App Engine and Cloud Run, and
the load balancer's URL map can move individual path groups without another DNS
change. Configure both HTTP and HTTPS frontends while legacy clients require
plain HTTP. Do not introduce an HTTP redirect until the C client behavior has
been tested.

### Parallel-run topology

The replacement stack is built beside the live stack, not in place of it:

```text
retrostore.org
      │
      ▼
External Application Load Balancer
      ├── initially 100% ──► App Engine (authoritative)
      └── after approval ──► Cloud Run route groups

next.retrostore.org ───────► Flask compatibility API candidate
admin-next.retrostore.org ─► Flask admin candidate

App Engine/Objectify ── idempotent sync ──► Firestore/Cloud Storage mirror
         │                                      │
         └──────── differential comparator ─────┘
```

The exact candidate hostnames remain configurable, but they must be distinct
from production. Existing clients remain on `retrostore.org`. The legacy admin
is the only production catalog writer while App Engine is authoritative. The
new admin uses isolated staging data for mutation tests and may expose a
read-only view of the synchronized production mirror before cutover.

The Objectify exporter/importer becomes a repeatable synchronization job during
the parallel run. It exports new or changed entities, copies missing or changed
objects, and idempotently updates the Firestore/Storage mirror. Each run records
its source high-water mark, entity and byte counts, checksums, failures, and
completion time. A final writer freeze and synchronization close the remaining
lag before authority changes.

### Differential comparison

A scheduled Cloud Run Job or equivalent isolated comparator sends the same
read-only request corpus to App Engine and the Flask candidate. It compares:

- HTTP status, content type, CORS behavior, and error behavior.
- Decoded protobuf fields, defaults, ordering, and repeated values. Serialized
  field order may differ unless a real consumer proves the raw ordering matters.
- Catalog filtering, search, pagination, media selection, and placeholders.
- Media metadata, byte lengths, checksums, and exact raw range bytes.
- Stable screenshot behavior by downloading and hashing the resulting images
  when the approved URL host or path is intentionally different.

The corpus covers every app ID plus invalid IDs, all meaningful `listApps`
filter and pagination boundaries, every app/media-type combination, and every
media object with boundary and invalid region reads. Any intentional difference
must be narrow, documented, reviewed, and added to an approved allowlist. A
sample of traffic is useful operational evidence but does not replace this
complete-corpus comparison.

Real state requests are never replayed to the candidate endpoint. Synthetic
state lifecycle tests upload separate fixtures to both stacks, allow the
allocated tokens to differ, and compare decoded downloads and range behavior.
The migration job may copy active state records as data, without invoking the
candidate API or allocating a second token. Before state cutover, migrate all
active state records and provide a tested reverse export/synchronization path so
states created on the new stack can survive a rollback.

### Production route groups

Test the load balancer on a separate hostname first. Then point
`retrostore.org` at it while its URL map still routes 100% of production traffic
to App Engine. Soak and validate that front-door change independently from any
backend migration. Subsequent cutover and rollback operations are URL-map
changes, not DNS changes.

Use these route groups and dependency rules:

| Order | Route group | Cutover rule |
| --- | --- | --- |
| 1 | Static website | Independent after asset and routing checks |
| 2 | Catalog reads | Canary gradually after zero-diff gates pass |
| 3 | Media reads and assets | Canary gradually after checksum/range parity |
| 4 | Admin and catalog writes | Atomic writer handoff; never dual-write |
| 5 | All three state endpoints | Move atomically after active-state migration |
| 6 | Firmware and remaining legacy routes | Move only after route-specific parity |

Catalog and media reads can use controlled traffic increments once their gates
pass. Admin writes cannot canary across two writers: freeze the old admin, run a
final sync, verify it, and enable the new admin as the sole writer. The three
state endpoints form one atomic route group so token allocation, upload, and
download never split across authorities.

### Public compatibility API service

`retrostore-api-compat` is a Flask application running behind Gunicorn. It
should:

- Be independently built and deployed from the admin service.
- Generate Python protobuf classes from the frozen API 0.2.13 schema.
- Accept protobuf and the supported legacy JSON request forms.
- Preserve response status codes, headers, error messages, media ordering, and
  raw-byte responses.
- Remain unauthenticated for existing clients.
- Use only stateless, concurrency-safe request handling.
- Treat caches as optional performance optimizations, never as correctness or
  allocation mechanisms.
- Use Cloud Storage range reads internally while retaining the legacy
  protobuf-request/raw-response contract externally.
- Expose structured logs and latency/error metrics for every API method without
  logging state data or application binaries.

Any future improved API should use an explicitly versioned route. The legacy
`/api/*` behavior should not be silently changed.

### Server-rendered admin application

`retrostore-admin` serves both the HTML interface and its administrative
operations. It should not require a separate JSON API for its own pages.

The UI stack is:

- Flask routes and ordinary GET/POST form handling.
- Jinja base layouts, page templates, partials, and macros.
- Tailwind CSS compiled to a static file during the build.
- htmx for selected HTML-fragment updates.
- Small vanilla JavaScript modules for upload previews or optional drag-and-drop.

Core routes should follow conventional server-rendered patterns:

```text
GET  /admin/apps
GET  /admin/apps/new
POST /admin/apps
GET  /admin/apps/{appId}
POST /admin/apps/{appId}
POST /admin/apps/{appId}/media
POST /admin/apps/{appId}/screenshots/{screenshotId}/move
POST /admin/apps/{appId}/delete

GET  /admin/users
POST /admin/users
POST /admin/users/{uid}/role

GET  /admin/firmware
POST /admin/firmware
```

Mutations use POST followed by a redirect. Server-side validation rerenders the
form with entered values and field-level errors. Screenshot ordering must work
with accessible move-up and move-down controls; drag-and-drop can be an optional
enhancement.

Initial uploads should use ordinary multipart forms and stream through the admin
service to Cloud Storage. Signed or resumable direct uploads can be added later
if observed file sizes or request limits justify the extra coordination.

### Firebase Authentication and sessions

The login page uses the Firebase client SDK for sign-in. It then sends the ID
token and a CSRF token to a session-login endpoint. The Flask service exchanges
the ID token for a secure Firebase session cookie and clears client-side auth
state.

Every protected request must:

- Verify the session cookie and revocation state as appropriate.
- Enforce CSRF protection on mutations.
- Load or validate the user's role.
- Enforce publisher ownership for app, media, and screenshot changes.

Roles include at least administrator and publisher. Firebase custom claims may
carry coarse roles, while user profiles, publisher ownership, and audit metadata
remain in Firestore.

### Firestore database strategy

The existing `(default)` database is expected to be Datastore mode because it is
used by App Engine/Objectify. Its actual mode, location, and configuration must
be confirmed during inventory.

Create two named Firestore Standard edition databases in Native mode:

| Database ID | Purpose |
| --- | --- |
| `retrostore` | Durable catalog, users, firmware metadata, and audit events |
| `retrostore-state` | Ephemeral public system-state tokens and payloads |

The database location must be selected only after the current App Engine,
Datastore, and Storage locations are inventoried. Enable delete protection for
the durable metadata database. Keep the existing Datastore-mode database
unchanged and read-only after final synchronization through the rollback window.

Separating state data allows the public API service to write state documents
without granting it write access to durable catalog metadata.

### Firestore catalog model

Use top-level collections that preserve existing identifiers and make migration
relationships explicit:

```text
apps/{appId}
authors/{authorId}
media/{mediaId}
screenshots/{screenshotId}
users/{firebaseUid}
firmware/{firmwareId}
auditEvents/{eventId}
```

An app document contains API-facing metadata and ordered references:

```json
{
  "name": "Armored Patrol",
  "version": "1.0",
  "description": "...",
  "platform": "TRS80",
  "model": "MODEL_I",
  "categories": ["GAME"],
  "releaseYear": 1981,
  "authorId": "123",
  "authorName": "John Doe",
  "publisherUid": "firebase-user-id",
  "publisherEmail": "publisher@example.com",
  "mediaSlots": {
    "disks": ["1001", null, null, null],
    "cassette": null,
    "command": "1002",
    "basic": null
  },
  "screenshotIds": ["shot-1", "shot-2"],
  "firstPublishedAt": "timestamp",
  "updatedAt": "timestamp"
}
```

Design rules:

- Preserve existing app IDs.
- Preserve existing media and author IDs where practical.
- Preserve the exact four-disk ordering and optional cassette, command, and
  BASIC slots.
- Store screenshot ordering explicitly on the app document.
- Store original filenames as metadata, never as trusted object paths.
- Denormalize `authorName` into app documents for catalog reads while preserving
  `authorId` as the relationship.
- Use Firestore timestamps internally and convert to the legacy integer format
  only at the API boundary.
- Store checksums, object paths, sizes, content types, upload timestamps, and
  descriptions on media and screenshot documents.

Catalog search can initially load the small catalog and reproduce the existing
deterministic filtering, sorting, and pagination in Python. A dedicated search
product is not justified at the current scale.

### System-state model

State-token metadata lives in `retrostore-state`; normalized protobuf payloads
live in a separate private state bucket:

```text
states/{token}
  objectPath: string
  size: integer
  sha256: string
  createdAt: timestamp
  expiresAt: timestamp
```

This split is required for compatibility. The legacy validator caps each memory
region's data below 1,000,000 bytes but does not cap the region count or
aggregate payload. Matching isolated Java and Flask tests accept two maximum
regions in a 2,000,028-byte protobuf request. Thirty-three such regions
serialize to 33,000,432 bytes. [Cloud Run](https://docs.cloud.google.com/run/quotas)
documents a 32 MiB HTTP/1 request ceiling, while
[App Engine](https://docs.cloud.google.com/appengine/docs/standard/how-requests-are-handled)
documents a 32 MB request limit. A
[Firestore document is limited to 1 MiB](https://firebase.google.com/docs/firestore/quotas).
The payload therefore cannot safely be an inline Firestore field.

Allocation should:

1. Select a random token between `100` and `999`.
2. Transactionally read its document.
3. Claim it if it is absent or logically expired.
4. Retry on collision.

Upload the normalized state to a unique immutable object before transactionally
claiming a token that references it. A failed claim may retry with the same
object; a terminal failure deletes that object. Token reuse must never overwrite
an older object's path. Downloads reject logically expired documents before
reading the object and verify its size and checksum.

Configure `expiresAt` as a Firestore TTL field, but never rely on physical TTL
deletion for correctness. The application must treat a document as expired
based on its timestamp because TTL deletion is asynchronous. Add an eight-day
Cloud Storage lifecycle rule as eventual cleanup and explicitly delete replaced
or abandoned objects where practical.

### Cloud Storage model

Cloud Storage for Firebase is the object store. The Flask services should access
it through the official Python Google Cloud Storage client and their Cloud Run
identities.

Use a dedicated private assets bucket or a clearly isolated existing bucket,
selected after the project and location inventory. Use immutable object paths
that do not depend on user-controlled names:

```text
media/{appId}/{mediaId}/{sha256}
screenshots/{appId}/{screenshotId}/{sha256}.{ext}
firmware/{device}/{revision}/{version}/{sha256}.bin
states/{objectId}/{sha256}.pb
imports/{uploadId}
migration/{runId}
```

The original filename, content type, size, checksum, and upload timestamp live in
Firestore. App names, publisher email addresses, and uploaded filenames must not
be used to construct object paths.

Objects should remain private. Media is returned through the compatibility API,
and admin access is authorized by the Flask service.

Use a dedicated state-payload bucket so its short lifecycle and API-service
write permissions cannot affect durable catalog assets. Never place state
payloads under a publicly cacheable or Firebase download-token URL.

Public screenshot URLs should use a RetroStore-owned stable URL:

```text
https://retrostore.org/assets/screenshots/{screenshotId}
```

The asset handler can stream or redirect to the private object and set long
cache headers. A CDN can be added later without changing the API-visible URL. Do
not make Firebase download-token URLs the permanent public contract.

### Authorization and IAM

Server-side Firestore and Storage libraries use IAM rather than Firebase client
Security Rules. Browser Firestore and Storage access should be denied by
default.

Target permissions are:

```text
retrostore-admin service account:
  retrostore database      read/write
  retrostore-state         no access
  assets bucket            read/write
  state bucket             no access

retrostore-api service account:
  retrostore database      read-only
  retrostore-state         read/write
  assets bucket            read-only
  state bucket             read/write/delete
```

Use Application Default Credentials in Cloud Run. Do not create or deploy
downloaded service-account key files.

## Migration phases

### Phase 0: Contract freeze and infrastructure inventory

1. Copy the canonical protobuf schema into the new backend source tree and
   record its upstream version and checksum.
2. Document each endpoint's accepted methods, request formats, response format,
   status codes, headers, error behavior, ordering, and size limits.
3. Inventory public routes outside `/api/*`, including public RPC data,
   downloads, reports, screenshots, firmware/card endpoints, and redirects.
4. Inventory Firestore database IDs, modes, editions, locations, concurrency
   modes, and deletion protection.
5. Inventory Datastore entity kinds and counts, Blobstore objects, Cloud Storage
   buckets, serving URLs, firmware, state records, and orphaned references.
6. Confirm App Engine, Cloud Run candidate, Firestore, and Storage locations.
7. Pin the legacy Java toolchain sufficiently to run tests and the migration
   exporter reproducibly.
8. Inventory current DNS, certificates, HTTP/HTTPS behavior, load-balancing
   configuration, and every hostname used by deployed clients.
9. Define route groups, candidate hostnames, comparison-report retention, and
   the production routing rollback procedure.

Exit criteria:

- Every externally reachable route has an owner and migration disposition.
- Every stored entity kind and binary store has a migration disposition.
- The database and bucket locations for new resources are agreed.
- The API contract document is reviewed.
- The current front door and intended load-balancer topology are documented.
- No production behavior is intentionally changed.

### Phase 1: Compatibility suite and Python foundation

1. Capture golden requests and responses from the current App Engine service.
2. Add tests for all nine protobuf calls and all three legacy JSON request forms.
3. Test HTTP status, content type, CORS headers, and raw byte lengths.
4. Cover invalid input, missing apps, missing media slots, filtering, pagination,
   ordering, range truncation, and state-memory overlap behavior.
5. Exercise the JVM SDK, KMP/Wire client, C SDK, and embedded legacy C request
   format against the same test server.
6. Add fixtures that establish the largest accepted media and state payloads.
7. Create the locked Python project, generate protobuf classes, and add Flask
   application skeletons for both services.
8. Run tests against local Firestore and Storage emulators or isolated test
   resources without using production data.
9. Add a read-only production canary for safe catalog and media-reference calls.
10. Build the comparator harness, semantic protobuf normalizer, approved-diff
    format, and machine-readable comparison report.

Exit criteria:

- The suite passes against App Engine and defines the compatibility baseline.
- Golden fixtures are reviewed and versioned.
- The Python build and test suite are reproducible in CI.
- Generated protobuf code is traceable to the canonical schema.
- The comparator can run the baseline corpus against two configurable hosts.

### Phase 2: Provision Firebase persistence and establish the mirror

1. Create the named `retrostore` and `retrostore-state` Firestore Native
   databases in the agreed location.
2. Enable delete protection on the durable database and configure TTL for state
   documents.
3. Create or designate the private durable-assets and ephemeral-state buckets,
   apply service-account IAM, and configure state-object lifecycle cleanup.
4. Build a read-only Java exporter that converts Objectify entities into a
   versioned, normalized migration format.
5. Export app metadata, authors, users, media relationships, firmware, active
   states, and Blobstore references.
6. Copy binaries into immutable Cloud Storage paths and calculate checksums.
7. Import normalized documents into Firestore while preserving IDs and ordering.
8. Verify entity counts, byte counts, checksums, references, and generated API
   responses.
9. Make export, copy, and import idempotent and incremental so they can maintain
   the mirror throughout the parallel-run period.
10. Record a source high-water mark and a reconciliation report for every sync.
11. Schedule synchronization while retaining the legacy admin as the sole
    production catalog writer.

Exit criteria:

- Every referenced binary is present and checksum-verified in Cloud Storage.
- Every durable entity has a normalized Firestore representation.
- Active state records can be migrated without token collisions.
- Referential-integrity and API-fixture comparisons pass.
- Repeated syncs converge without duplicates, lost updates, or unexplained
  checksum differences.
- The legacy database and objects remain untouched and usable for rollback.

### Phase 3: Build candidate services and run them in parallel

1. Implement the Flask/Jinja/Tailwind admin shell and conventional form routes.
2. Configure Firebase Authentication, ID-token exchange, session cookies,
   logout, revocation handling, and CSRF protection.
3. Implement explicit administrator/publisher authorization and ownership.
4. Implement app, author, media, screenshot, user, firmware, and import workflows
   against the new Firestore and Storage model.
5. Add audit events and integration tests for every mutation.
6. Implement all legacy endpoints in `retrostore-api-compat`, including legacy
   JSON parsing and protobuf response behavior.
7. Deploy the API candidate to `next.retrostore.org` and the admin candidate to
   `admin-next.retrostore.org`, or the agreed equivalent hostnames.
8. Exercise admin mutations only against isolated staging data. Against the
   synchronized production mirror, keep the new admin read-only.
9. Run the complete differential corpus on a schedule and after every service,
   schema, or migration change.
10. Run synthetic state lifecycle comparisons without duplicating real writes.
11. Add dashboards for synchronization lag, comparison failures, per-method
    traffic, latency, response sizes, and errors.
12. Resolve every unexplained difference and restart the agreed zero-diff soak
    after any material compatibility fix.

Exit criteria:

- Admin workflows have feature parity, authorization tests, and staging mutation
  coverage.
- The complete read corpus has zero unexplained differences.
- Current KMP/JVM, web, C, and embedded JSON clients pass candidate-host tests.
- Synchronization lag and failures are visible and within agreed thresholds.
- App Engine remains authoritative and no production URL has moved.

### Phase 4: Introduce the production front door and rehearse rollback

1. Create a global external Application Load Balancer with serverless network
   endpoint groups for App Engine and the Cloud Run services.
2. Configure HTTP and HTTPS frontends, certificates, host rules, and an initial
   URL map that sends every production route to App Engine.
3. Validate the load balancer through a separate test hostname, including plain
   HTTP behavior, CORS, large bodies, raw range responses, and client libraries.
4. Point `retrostore.org` at the load balancer while it still routes 100% of
   production traffic to App Engine.
5. Soak the front-door change independently and verify logs, monitoring,
   certificates, cache behavior, latency, and rollback.
6. Rehearse URL-map rollback for every route group without changing data
   authority.
7. Build and test reverse export/import for catalog changes and states created
   on the new stack. The procedure must freeze the new writer, preserve IDs and
   objects, reconcile the legacy store, and restore exactly one legacy writer.

Exit criteria:

- The production hostname has completed its App Engine-only load-balancer soak.
- All current clients behave identically through the new front door.
- Every route group has a tested, timed, and documented routing rollback.
- State rollback preserves states created after a future cutover.
- App Engine is still the sole production backend and data authority.

### Phase 5: Verified production cutover

1. Confirm every production go/no-go gate and record the approval and comparison
   report versions used for the decision.
2. Put the legacy admin into read-only mode and run a final incremental sync,
   checksum reconciliation, and API comparison.
3. Move the static website, then catalog reads, then media reads/assets. Use
   controlled traffic increments where the load balancer supports safe canaries.
4. After those read groups are stable, enable the new admin as the sole catalog
   writer and permanently disable legacy admin mutations.
5. Continue comparison against a frozen or safely refreshed legacy reference and
   monitor new catalog writes through the Flask API.
6. Migrate and verify every active state, briefly quiesce state writes if needed,
   and switch upload, download, and region endpoints atomically.
7. Move firmware and remaining legacy routes only after their route-specific
   compatibility gates pass.
8. Preserve HTTP, HTTPS, CORS-simple POST, custom-domain behavior, legacy data,
   and reverse-sync capability throughout the observation window.

Routing rollback consists of returning the affected route group to App Engine in
the URL map. Data rollback must also restore a single writer: freeze the new
admin before re-enabling the legacy admin, reverse-sync any post-cutover catalog
changes, and reverse-sync new active states before returning the atomic state
group. No rollback relies on a destructive reverse migration.

Exit criteria:

- All public traffic is served by Cloud Run for the agreed observation period.
- Error rates and latency remain within agreed thresholds.
- Current KMP/JVM, web, C, and embedded JSON clients pass end-to-end production
  smoke tests.
- No unexpected writes occur in the legacy database.
- Routing and data rollback remain available until the observation window ends.

### Phase 6: App Engine retirement

1. Confirm no traffic remains on App Engine-only routes.
2. Remove the cron keep-alive ping.
3. Permanently disable the legacy admin and upload handlers.
4. Archive deployment configuration, normalized exports, and migration reports.
5. Retain legacy database and object backups for the agreed recovery period.
6. Disable App Engine only after the rollback window closes.
7. Delete legacy data only under a separate reviewed retention plan.

## Compatibility test matrix

At minimum, each endpoint needs tests for:

| Dimension | Required cases |
| --- | --- |
| Request encoding | Protobuf; legacy JSON where supported |
| Transport | HTTPS; HTTP while still supported |
| Browser behavior | Headerless simple POST; valid optional preflight |
| Response | Success; semantic failure; malformed input |
| Catalog | Ordering; filtering; pagination; empty results |
| Media | Fixed slot order; placeholders; type filters; filename preservation |
| Region reads | Exact range; EOF truncation; missing/invalid token |
| State | Upload/download; expiry; token exhaustion; overlapping memory ranges |
| Size | Largest accepted media and state requests and responses |
| Protocol | Status code; content type; CORS; protobuf fixture compatibility |

Protobuf evolution rules for the compatibility API:

- Never renumber or reuse an existing field number.
- Never change the meaning or encoding of an existing field.
- Treat current default values and absent fields as observable behavior.
- Additive fields must be tested with old generated clients before release.
- Compare decoded protobuf semantics unless exact serialized ordering is itself
  proven to be required by a consumer.

## Admin test matrix

The server-rendered admin requires tests for:

- Anonymous access redirects to login.
- ID-token exchange and secure session-cookie behavior.
- CSRF rejection for every mutation.
- Administrator and publisher role boundaries.
- Publisher ownership on app, media, and screenshot operations.
- Server-side validation and preservation of entered form values.
- App creation, editing, deletion, and author handling.
- Four-disk slot ordering plus cassette, command, and BASIC media.
- Upload validation, checksums, replacement, deletion, and orphan cleanup.
- Screenshot upload, ordering, stable URLs, and deletion.
- Firmware upload and version handling.
- Audit-event creation for successful and rejected sensitive operations.

## Production go/no-go gates

"100% sure" means that all agreed evidence is green and no known high-severity
issue remains; it does not mean relying on an uneventful small canary. Before
the first production backend route moves from App Engine, require:

- 100% of expected durable entities and active states are accounted for.
- Every referenced object exists with matching size and checksum, with zero
  broken or orphaned references outside a reviewed cleanup list.
- The complete comparison corpus has zero unexplained API differences.
- Scheduled comparisons have zero unexplained differences for an agreed
  continuous soak, provisionally two to four weeks. Any material fix restarts
  the relevant soak clock.
- JVM, KMP Android/iOS/web, C, and embedded legacy JSON consumers pass against
  the candidate host and through the production load balancer.
- Browser-origin CORS, headerless POST, optional preflight, and plain port-80
  behavior pass from representative production environments.
- Synthetic upload/download/region state lifecycles, expiry, overlap, boundary,
  and invalid-range cases pass.
- Every admin workflow, role boundary, ownership rule, upload, and authentication
  lifecycle passes against an isolated production-like environment.
- Cold starts, concurrency, timeouts, payload limits, sustained load, and cost
  are within agreed thresholds.
- Dashboards and alerts cover sync lag, comparison failures, errors, latency,
  state allocation, and storage/data-integrity failures.
- URL-map rollback has been rehearsed for every route group, and both catalog
  writer rollback and state reverse synchronization have been rehearsed before
  their corresponding authority changes.
- There are no unresolved severity-one or severity-two defects, security
  blockers, data-loss risks, or unapproved differences.

Each cutover group also needs a signed comparison report, a named decision owner,
an observation window, rollback thresholds, and an operator available to execute
the rollback. If a gate fails, traffic stays on or returns to App Engine.

## Security and operational requirements

- Remove the first-login administrator bootstrap after explicit admins exist.
- Require verified Firebase session cookies for every admin page and operation.
- Enforce CSRF protection on login exchange, logout, and every mutation.
- Enforce publisher ownership for media and screenshot mutations.
- Deny direct browser access to Firestore and Cloud Storage by default.
- Use least-privilege service accounts for the two Cloud Run services.
- Use Application Default Credentials and never deploy service-account keys.
- Keep the compatibility API public; do not add an authentication requirement to
  legacy clients.
- Apply rate limits conservatively and test them against embedded clients.
- Validate upload sizes, content types, filenames, and decoded file formats where
  appropriate.
- Record administrative actor, target, timestamp, and result in an audit log.
- Avoid logging Firebase tokens, session cookies, protobuf state payloads, or
  binary media.
- Use unique immutable object paths so failed metadata commits only create
  detectable orphan objects, never overwrite referenced data.
- Make mutation handlers idempotent where retries are possible.

## Known risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Undocumented client behavior | Golden tests and real SDK consumer tests |
| Legacy C client requires plain HTTP | Preserve port 80 or migrate and validate the client first |
| Browser CORS preflight breaks | Preserve headerless POST and add tested `OPTIONS` handling |
| Python protobuf serialization differs in byte order | Compare decoded semantics and test real clients |
| Media order or placeholder behavior changes | Golden protobuf fixtures and semantic order assertions |
| Objectify nested values are not language-neutral | Versioned one-time Java exporter and normalized import |
| App Engine serving image URLs disappear | Stable RetroStore asset URLs and verified Storage migration |
| Firebase download tokens become an accidental contract | Return only RetroStore-owned asset URLs |
| State tokens collide during cutover | Import active states and cut state endpoints together |
| Real state shadowing duplicates side effects | Compare only isolated synthetic lifecycles; never replay user writes |
| Firestore TTL deletion is delayed | Enforce logical expiry in Flask before allocation or download |
| Public API write identity can alter catalog | Separate state and durable metadata databases with distinct IAM |
| Storage and Firestore writes are not atomic | Immutable objects, idempotent commits, and orphan reconciliation |
| Instance-local caches cause inconsistent results | Stateless correctness; cache only immutable/read-through data |
| Admin rewrite expands project scope | Conventional forms and separate, independently deployable services |
| New database migration loses data | Idempotent export/import, checksums, parity tests, and untouched legacy store |
| Mirror lag hides a recent admin change | Keep App Engine authoritative, track high-water marks, freeze the old writer, and run a final reconciliation |
| Comparator reports harmless protobuf or URL differences | Normalize decoded semantics and use a narrow, reviewed allowlist with content-hash checks |
| Load-balancer or DNS migration is confused with backend cutover | Test on a candidate hostname, then soak production while still routing 100% to App Engine |
| Routing rollback loses writes made after authority changed | Freeze writers and rehearse reverse catalog/state synchronization before cutover |
| Two admin services create conflicting writes | Keep the candidate read-only on production data and perform an atomic single-writer handoff |

## Decisions still to make

- Whether plain HTTP support is retained indefinitely or formally deprecated
  after all C clients have moved to HTTPS.
- The public static website bucket's CDN, cache-invalidation, and deployment
  policy. It must remain separate from the private application-assets bucket.
- Approve the inventory-derived location proposal: `nam5` for named Firestore
  databases, `US` for the private assets bucket, and `us-central1` for Cloud Run.
- Whether to use the existing Firebase Storage bucket or create a dedicated
  private production assets bucket.
- The retention period for uploaded system states, normalized migration exports,
  and legacy backups.
- Whether application reports continue through email or become an admin queue.
- Whether stable screenshot URLs are initially served by Flask or routed through
  a CDN from the first release.
- The exact candidate API and admin hostnames.
- The required zero-diff soak duration; the provisional recommendation is two
  to four continuous weeks after the last material compatibility change.
- The traffic increments, observation duration, and automatic rollback
  thresholds for catalog and media read canaries.
- Who has go/no-go authority for each route group and who operates rollback.

These decisions do not block contract capture, the Python project skeleton, or
the read-only infrastructure inventory.

## Immediate next milestone

The first implementation milestone is Phase 0 plus the read-only portion of
Phase 1:

- [x] Add the canonical protobuf schema and API contract registry.
- [x] Establish the locked Python project and two Flask application skeletons.
- [x] Pin the legacy Java toolchain sufficiently to run baseline tests and build
  the migration exporter.
- [x] Expand the initial safe baseline into representative golden success,
  boundary, malformed, catalog, and media cases.
- [x] Run and repeat the expanded suite against App Engine with zero differences.
- [x] Add every-app/media coverage, JVM/KMP/embedded-C client runs, and isolated
  synthetic state lifecycle and oversized-payload cases.
- [x] Run the expanded suite against the local Flask candidate with zero
  differences across all 45 reviewed scenarios.
- [x] Produce the route and read-only cloud infrastructure inventory.
- [x] Build a repeatable read-only exporter/reconciler for representative
  Objectify encodings, binary sizes and checksums, and reference integrity.
- [x] Implement, test, and deploy the sanitized App Engine-side
  Blobstore-content and live Search-index inventory operation without promotion.
- [x] Capture and reconcile two matching reports from the reviewed,
  non-promoted App Engine version, then delete all temporary versions.
- [x] Add the strict approved-difference format with exact fingerprints, named
  ownership, expiry, and stale-approval rejection.
- [x] Define and validate the normalized catalog/media/screenshot mirror format
  and prove its storage adapter against all 45 reviewed observations.
- [x] Build the read-only Java Objectify exporter for that format, including
  binary manifests and explicit dangling-reference reconciliation.
- [x] Add a tightly controlled admin-only execution path, deploy it without
  promotion, capture the first sensitive export locally, validate it through
  the Python archive loader, and delete the temporary version.
- [x] Run the complete 158-scenario corpus against the synchronized candidate
  mirror. The corpus, method registry, semantic normalizer, baseline, two-host
  comparator, and approval gate are implemented; two complete App Engine
  captures and the archive-backed local candidate matched with zero differences.
- [ ] Finalize candidate hostnames, the load-balancer URL map, route groups,
  monitoring thresholds, and named rollback owners. Current DNS, certificates,
  HTTP behavior, and absence of an existing load balancer are documented.

The unfinished Arduino tree is not a working public API consumer and remains
outside the compatibility gate; leave it untouched unless a known hardware
deployment requires a separately scoped repair. The next executable milestone
is the next Phase 2 slice: define the isolated Firestore/Storage resource names,
location, lifecycle, and retention policy, then implement the cloud adapter and
controlled import. Database and bucket creation remains a deliberate operator
action after those choices are approved.

No production data, Firebase configuration, or routing should change during this
milestone.

## Reference documentation

- [Cloud Run Flask quickstart](https://docs.cloud.google.com/run/docs/quickstarts/build-and-deploy/deploy-python-service)
- [Flask templates](https://flask.palletsprojects.com/en/stable/tutorial/templates/)
- [Flask Blueprints](https://flask.palletsprojects.com/en/stable/blueprints/)
- [Tailwind CLI](https://tailwindcss.com/docs/installation/tailwind-cli)
- [htmx documentation](https://htmx.org/docs/)
- [Firebase session cookies](https://firebase.google.com/docs/auth/admin/manage-cookies)
- [Firebase custom claims](https://firebase.google.com/docs/auth/admin/custom-claims)
- [Manage multiple Firestore databases](https://firebase.google.com/docs/firestore/manage-databases)
- [Choose Firestore Native or Datastore mode](https://docs.cloud.google.com/datastore/docs/firestore-or-datastore)
- [Firestore Security Rules and server IAM](https://firebase.google.com/docs/firestore/security/rules-structure)
- [Firestore TTL policies](https://firebase.google.com/docs/firestore/ttl)
- [Firestore quotas and limits](https://docs.cloud.google.com/firestore/quotas)
- [Cloud Storage for Firebase and Google Cloud integration](https://firebase.google.com/docs/storage/gcp-integration)
- [App Engine bundled-service migration](https://docs.cloud.google.com/appengine/migration-center/standard/services/migrating-services)
- [App Engine and Cloud Run comparison](https://docs.cloud.google.com/appengine/migration-center/run/compare-gae-with-run)
- [Cloud Run service model](https://docs.cloud.google.com/run/docs/overview/what-is-cloud-run)
- [Serverless network endpoint groups](https://docs.cloud.google.com/load-balancing/docs/negs/serverless-neg-concepts)
- [Load-balancer URL maps](https://docs.cloud.google.com/load-balancing/docs/url-map-concepts)
- [External Application Load Balancer use cases](https://docs.cloud.google.com/load-balancing/docs/https/use-cases)

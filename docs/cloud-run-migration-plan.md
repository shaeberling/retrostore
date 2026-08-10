# RetroStore Modernization and App Engine Migration Plan

Status: In progress

Last updated: 2026-08-10

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
  unreferenced Blobstore objects, which have now been separately classified.
- A protected, create-only Blobstore classifier reconciled those eight objects
  against all 90 referenced screenshots without exposing identifiers in the
  repository. All eight are image uploads totaling 182,036 bytes and each is a
  size+MD5 duplicate of exactly one referenced screenshot. The prior App Engine
  byte scan proves every metadata MD5 matches its content, and an independent
  archive check proves all eight corresponding byte sequences are already in
  the retained normalized catalog export. No additional object copy or legacy
  content fetch is required; no Blobstore object was changed or deleted.
- A protected read-only user reconciliation now compares all 10 legacy user
  records, all 32 publisher references, Firebase Auth, and the isolated admin
  role profiles. One verified Firebase administrator already matches; seven
  `NO_ACCOUNT` records are catalog attribution only; two unmatched historical
  administrators require manual review. An identity-free planner proposes no
  automatic account creation and has no write path. The proposed historical
  profile policy is recorded in `docs/legacy-user-migration.md` for approval.
- The public `/downloadapp` compatibility handler is now implemented against
  the normalized mirror. It preserves legacy errors, content types, CORS,
  attachment naming, case-insensitive typed downloads, and complete ZIP entry
  bytes. A read-only exhaustive run compared 32 ZIP downloads plus 62 typed and
  error scenarios against App Engine: all 94 matched semantically. ZIP envelope
  timestamps/compressor bytes are deliberately normalized because the legacy
  service regenerates them on every request. No route or traffic changed.
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
- A separate revision- and checksum-verified consumer build now runs the
  published JVM SDK 0.2.13 through all nine methods, compiles the reviewed
  TRS-80 Kotlin Multiplatform client through its five calls, and compiles the
  native C client through all three legacy JSON calls and nanopb decoding. The
  exact reviewed TRS-80 application revision also pins its protobuf, shared
  wiring, and Android, iOS, and browser HTTP transports. All pass over real
  loopback HTTP against the Flask candidate, including isolated state writes.
  The canonical local checkout at
  `/Users/sascha/source/TRS-80` was audited at revision
  `aecbddcc7f5515fb844bb7a1fc350d8ffaaf5ce5` on 2026-08-08. Its iOS simulator
  tests, Android shared/app compilation, and production web distribution all
  passed without changing that worktree.
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
  document limit.
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
- The isolated persistence topology is approved and provisioned. Named Standard
  Firestore Native databases `retrostore` and `retrostore-state` are in `nam5`;
  deletion protection is enabled on the durable database and
  `states.expiresAt` TTL is enabled on the state database. Private `US` buckets
  `trs-80-retrostore-assets` and `trs-80-retrostore-state` enforce uniform IAM
  and public-access prevention. Durable assets retain seven-day soft-delete
  recovery; state payloads disable soft delete and expire through an eight-day
  lifecycle. One synthetic 34-byte smoke-test state now exercises the isolated
  state path and will expire through the same seven-day/eight-day controls.
- An idempotent catalog importer and production Google Cloud persistence
  boundary are implemented behind dependency injection. Immutable Storage
  writes use generation-zero preconditions and verify existing collisions;
  Firestore stages content-derived snapshots and exposes them only through a
  final atomic active-pointer batch after complete read-back reconciliation.
  The operator command is dry-run by default and requires explicit target names,
  source-project equality, `--apply`, and an exact project confirmation before
  writing. The validated production archive was imported through the keyless,
  database-scoped `retrostore-migrator` identity as snapshot
  `catalog-ec07d9d7c8d47c8a46b745fc82b8d7f231e905dc6b6f7e00f4375547cf303de8`.
  The first pass created all 150 objects totaling 12,738,856 bytes; an immediate
  retry created none, downloaded and checksum-verified all 150, and reused the
  identical snapshot with zero collisions.
- Separate migrator, public API, and administration service accounts now have
  exact named-database IAM conditions and bucket-level Storage roles. No new
  workload identity can access the legacy `(default)` database. The private,
  unrouted `retrostore-api-compat-candidate` service is deployed in
  `us-central1` on revision `state1`, using the API identity and
  immutable image digest
  `sha256:35cfa574d18696eb89aa2e99868938f9d7782541ff128fcd27dd10eb5da34ff4`.
  Cloud Run's invoker IAM check is explicitly enabled; unauthenticated probes
  return HTTP 403 and only the runtime identity and migration operator retain
  service-scoped invocation.
- The seven-day public state adapter is implemented and its guarded real-cloud
  smoke test passed through the runtime identity. Payloads use unique immutable
  generation-guarded objects; metadata uses transactional random claims in the
  legacy `100`-`999` token range; downloads enforce logical expiry and verify
  generation, size, and SHA-256 before parsing the protobuf. A separate guarded
  external HTTP probe now verifies upload, full download, memory-excluded
  download, and overlapping-region precedence without recording its token.
- The complete 158-scenario corpus was replayed against an in-process Flask
  candidate loaded from the live isolated resources through the exact
  `retrostore-api` identity. All 32 apps, 60 media objects, 60 byte-range reads,
  and 6,826,237 media bytes matched App Engine with zero differences and no
  approvals. This independently revalidated all 150 stored objects.
- The same 158-scenario corpus then passed through the deployed Cloud Run URL
  twice: once during the explicitly approved temporary public diagnostic and
  once after restoring private IAM using an audience-bound token minted for the
  exact runtime identity. The deployed private state lifecycle gate also passed.
  The temporary `allUsers` binding was removed and the public API returned HTTP
  403 afterward. The earlier apparent front-end 404 combined Flask correctly
  rejecting `/` with Cloud Run's documented reservation of some paths ending in
  `z`; operational routes now use `/health` and `/ready`. The complete Python
  suite now has 168 passing tests.
- The first server-rendered admin slice is implemented and deployed privately
  as `retrostore-admin-candidate` revision `compact1`. Jinja/Tailwind inventory,
  search, and detail pages read the same active mirror and expose no mutations.
  Firebase Authentication is initialized from checked-in configuration with
  Google Sign-In only; anonymous and password sign-in are disabled. Server
  sessions require recent sign-in, verified email, an administrator/publisher
  role, revocation checks, and CSRF validation. The initial custom claim is a
  bootstrap fallback; once a Firestore user profile exists, its role is
  authoritative and is re-checked on every protected request. The runtime's
  custom Firebase role contains only `users.createSession` and `users.get`.
  Private smoke tests
  passed health, readiness, login, compiled CSS, and the pre-session redirect;
  unauthenticated Cloud Run access returns HTTP 403. The browser login was then
  verified end to end through the private proxy with a Google-verified Firebase
  user, an explicit `administrator` claim, and a server-created session cookie.
  The candidate CSP permits only the Google/Firebase origins required by that
  flow and validates the configured Firebase authentication domain before using
  it as a frame source. An administrator-only Firebase identity inventory and
  role workflow are also available; publishers are denied, self-role changes
  are rejected, and each user-profile role change commits atomically with its
  audit event in the named `retrostore` database. No Firebase user-update IAM
  permission was added. The first isolated mutation workflow now creates
  top-level future-schema app and author documents plus an audit event in one
  transaction. Publisher ownership, server validation, CSRF, concurrency, and
  idempotent request IDs are enforced. The staged detail workflow also supports
  updates guarded by optimistic integer revisions and exact-name-confirmed
  deletion; every mutation is atomic with its audit event, while author records
  are retained because they may be shared. The same isolated detail workflow now
  owns all four disk positions plus cassette, command, and BASIC slots and an
  explicitly ordered screenshot list. Media and screenshot uploads are bounded,
  validated, written to private UUID/checksum-addressed immutable object paths,
  then transactionally linked with an app revision and audit event. Screenshot
  type is detected from file bytes and SVG is rejected. Replacements and deletes
  clean up superseded objects, and app deletion cascades through staged assets.
  These documents are separate from the versioned `catalogSnapshots` mirror and
  cannot affect public API responses. Media slots are presented as one compact,
  vertically ordered set of responsive horizontal rows for faster scanning and
  replacement. The complete authenticated browser lifecycle passed on
  2026-08-09: create, edit, media upload and replacement, two screenshot
  uploads and reorder, individual screenshot deletion, and confirmed app
  deletion. The sanitized read-only reconciler verified revision 7 with one
  media document, two ordered screenshot documents, and exactly three linked
  private objects totaling 10,285 checksum-verified bytes. It found no retained
  superseded media object. After screenshot and app deletion it found zero app,
  media, or screenshot documents and zero objects under both private prefixes,
  while all nine audit events and the contiguous revision chain through 8
  remained. A fresh deployed-candidate comparison then matched all 158 public
  scenarios with zero differences, proving the isolated lifecycle did not alter
  the API-visible snapshot. The deployed image digest is
  `sha256:18d60af5803a168e3132b5315f345e10d9f5c14e7e949b0f206f601b241d836f`.
- A guarded RPK import workflow is implemented locally for the isolated future
  schema. It preserves canonical historical app UUIDs, including UUIDv1 IDs;
  validates the entire legacy JSON package and every decoded asset before any
  catalog write; previews without server-side persistence; and requires the
  exact SHA-256-matched package to be re-uploaded for apply. Package publisher
  fields are informational only, while ownership is bound to the authenticated
  Firebase identity. Apply refuses staged ID collisions, writes all metadata and
  one audit event atomically, and removes newly uploaded immutable objects if
  the transaction fails. The synchronized catalog remains read-only. The
  complete Python suite now has 181 passing tests.
- The guarded RPK workflow is deployed privately on admin revision `rpk1`, image
  digest `sha256:29f340e38fc92375c624262586866cc47887f2988c97453ece48d9218977a424`,
  and passed its authenticated browser lifecycle on 2026-08-09. The preview
  request produced no staged app and no apply request. Applying the exact
  re-upload created revision 1 with two ordered media documents, one screenshot
  document, exactly three linked private objects totaling 120 checksum-verified
  bytes, and one `STAGED_RPK_IMPORTED` audit event. The sanitized reconciler
  found no extra document or object. The package publisher remained
  informational and ownership came from the authenticated session. The full
  deployed public corpus then matched all 158 scenarios with zero differences.
  Confirmed UI deletion removed the app, both media documents, the screenshot
  document, and all three objects; the import and delete audit events remain. A
  second post-cleanup comparison again matched 158/158 with no approvals or
  differences.
- The initial catalog working-set bridge is implemented. It deterministically
  converts the exact active immutable mirror into top-level app, author, media,
  and screenshot documents while preserving historical IDs, slots, ordering,
  timestamps, checksums, object paths, legacy screenshot URLs, and publisher
  email. No Firebase ownership is inferred from legacy email. Every source
  document is fingerprinted and marked `PUBLISHED`; the admin service and UI
  treat that baseline as read-only, including uppercase legacy application IDs,
  numeric media IDs, checksum-derived screenshot IDs, and extensionless legacy
  screenshot object paths. Materialization requires the dedicated migrator,
  exact project confirmation, and an archive that independently matches the
  active checksum-verified cloud snapshot. One atomic batch creates the source
  documents, `catalogWorkingControl/current`, and a sanitized audit event. It
  does not write objects or move `catalogControl/active`.
- The read-only guard is deployed privately on admin revision `working1`, image
  digest `sha256:fed3a29ce5b3b82d2f2208c4bc6b2d8f0843a408936b9e70df8a6aaf9b9d072e`.
  All readiness checks pass and anonymous invocation remains HTTP 403. The real
  active archive dry run produced 32 apps, 18 authors, 60 media records, and 90
  screenshots under materialization
  `working-85d72e7e7473dd9bb865ee08d7166acff00b7576074b4fc56eed47c7c1097b6e`.
  The dedicated migrator created the 200 source documents, control record, and
  one audit event atomically. An idempotent follow-up independently reloaded the
  active cloud mirror, verified every object checksum, reconciled all 200
  documents plus the single audit event, and created nothing. The active public
  snapshot remains
  `catalog-ec07d9d7c8d47c8a46b745fc82b8d7f231e905dc6b6f7e00f4375547cf303de8`.
  A post-materialization deployed comparison matched all 158 observations with
  zero differences and no approvals.
- The stage-only publication rehearsal is implemented and exercised against the
  live baseline. It loads the source documents from the working collections,
  reconciles the control and single audit event, validates every source
  fingerprint, checksum-verifies all 150 referenced objects totaling 12,738,856
  bytes, and rebuilds the exact active immutable snapshot. Both dry run and the
  confirmed stage-boundary invocation reported the same 32 apps, 60 media
  records, and 90 screenshots under snapshot
  `catalog-ec07d9d7c8d47c8a46b745fc82b8d7f231e905dc6b6f7e00f4375547cf303de8`.
  The snapshot store now rehashes every nested document even when a matching
  snapshot is already `READY`. The rehearsal command contains no activation
  operation and the active pointer did not move.
- The publication boundary now overlays isolated new apps and copy-on-write
  published metadata drafts onto the exact materialized baseline. Drafts live
  in a separate `appDrafts` collection, preserve baseline media/screenshots,
  carry the source snapshot and fingerprint, use optimistic revisions, and are
  audited on create/update/discard without changing a published source
  document. Candidate construction independently checks ownership, timestamps,
  authors, exact media slots, screenshot order, and every referenced object.
- A 2026-08-10 live read-only publication dry run found one existing isolated
  staged app and author, no staged media or screenshots, and derived a different
  33-app candidate
  `catalog-5b0bbf8bb683ed653d4583fa486589358ea759ff0e145f156bedb049b7cc04a2`.
  It made no writes; the 32-app active pointer remains
  `catalog-ec07d9d7c8d47c8a46b745fc82b8d7f231e905dc6b6f7e00f4375547cf303de8`.
- Private API revisions can now pin both the ID and digest of one explicit
  staged snapshot, while ordinary revisions continue to read the active
  pointer. New candidate screenshots have a configurable absolute origin and a
  short checksum-verified, CORS-enabled, immutable, strong-ETag serving route;
  every existing legacy screenshot URL remains unchanged. The absolute URL was
  checked against the Android, iOS, and web KMP fetch implementations, while
  the short production form fits the reviewed native URL-size expectation.
- Live route-order verification established that `/screenshotServe` is behind
  the legacy login gate. Anonymous requests with missing, invalid, and known
  valid Blobstore keys all return the same admin-login forwarding page. Its only
  source-tree consumer is the Polymer admin; the pinned KMP application has no
  reference and public API responses contain direct image-serving URLs. It is
  therefore classified with legacy-admin retirement, not as a public Images
  service compatibility route.
- Exact compare-and-swap activation and rollback are implemented behind a
  separate dry-run-first operator command. Apply requires the dedicated
  migrator, four exact confirmations, a transaction-time re-read and full hash
  of both snapshots, and an audit event. Rollback can target only a previously
  ready snapshot. Neither operation has been applied to the live catalog.
- The complete Python suite now has 224 passing tests on Python 3.14.6, and the
  compiled Tailwind admin asset is current.
- The 33-app candidate was then written as an immutable `STAGED` snapshot. A
  dry run of the guarded activation command reconciled both complete snapshots
  against their exact IDs and digests with `applied: false`; the active pointer
  remained unchanged. A separate private `retrostore-api-preview` service now
  pins that staged snapshot on revision `preview1`, image digest
  `sha256:1f265510a590a6a880b759626dfb94d6106c43aa2c8590963f1825b7c60aaeee`.
  It has no production route and no anonymous invoker. Its complete corpus
  matched 156/158 scenarios; the only two differences were the full and nano
  catalog pages, each adding exactly staged app
  `015488ef-d9e2-4437-9c38-519d10cb8585` and removing nothing. Every existing
  app, media response, and byte range matched. Its synthetic state upload,
  round trip, memory exclusion, overlap, and legacy token-range checks passed.
- Admin revision `draft1`, image digest
  `sha256:5649c2012818fedcb15f80ba0e742ddce9c2df23d928efa6809127b355300373`,
  is deployed privately with healthy readiness including the published-draft
  store. It provides audited copy-on-write metadata create/edit/discard without
  changing published source documents or the active snapshot.
- Copy-on-write draft assets are implemented and deployed privately as admin
  revision `draft2`, image digest
  `sha256:bf535aab9849638f84435a115b103e4607a109f48435b702fb086907459be99e`.
  Replacements use separate `appDraftMedia` and `appDraftScreenshots`
  collections with unique immutable objects. Removing inherited media or
  screenshots changes only the overlay; draft deletion cascades only
  draft-owned objects. Screenshot ordering, optimistic revisions, ownership,
  content verification, audit events, publication merging, and the compact
  server-rendered asset UI are covered. The complete Python suite has 234
  passing tests. All seven readiness checks, login, compiled CSS, redirect, and
  anonymous-denial smoke tests passed at zero percent before `draft2` received
  100% of private admin traffic. A post-promotion active API comparison matched
  158/158 scenarios with zero approvals. An authenticated asset mutation was
  deliberately not synthesized against a published app during unattended
  deployment; that browser review remains an operator-visible UI check.
- Front-door preparation is now checked in under `infra/front-door/`. The
  machine-readable plan keeps an App Engine-only production baseline, assigns
  every frozen API method to a route group, permanently pins the Card and
  TRS-IO route island to App Engine, and fails unclassified paths closed to App
  Engine. A separate threshold file requires hourly comparisons, fourteen
  continuous zero-diff days, zero integrity errors, staged read canaries, and
  atomic state/admin handoffs. Its safety validator runs in CI. Read-only cloud
  discovery on 2026-08-10 reconfirmed that no load-balancer resource exists and
  that Certificate Manager is not enabled. No resource was created.
- Privacy-safe request telemetry is deployed on private API revision
  `redirects1` (inheriting the `observability2` hardening) and admin revision
  `observability1`. Both were tested at zero
  traffic before promotion; the API
  still matched production 158/158 and the admin passed all readiness and
  browser-bootstrap smoke checks. The real JVM, pinned TRS-80 KMP, and embedded
  C clients also pass against the instrumented service. Cloud Logging parses
  the bounded events and trace correlation without application URLs, payloads,
  tokens, cookies, identities, or binary data.
- A private `retrostore-hourly-comparator` Cloud Run Job is deployed with a
  dedicated keyless identity, private candidate invocation, no database/state
  access, and conditional create-only access to
  `operations/comparisons/`. Its first manual execution retained a
  checksum-verified 158/158 report with zero approvals. A prefix-only 90-day
  lifecycle is applied, and an hourly UTC Cloud Scheduler trigger is enabled.
- Cloud Scheduler successfully started a second 158/158 execution. The migration
  dashboard, a passing-comparison log metric, and difference/stale-evidence
  alert policies are deployed. The policies are intentionally disabled and
  channel-free until the responsible recipient is confirmed.
- A recurring catalog-refresh command is implemented separately from the
  bootstrap importer. It compares normalized full exports, requires the exact
  active snapshot on apply, stages and reconciles immutable data, proves the
  active pointer did not move, and exposes no activation option. Its first
  real-cloud rehearsal reused all 150 baseline objects with zero differences
  and left the 32-app active snapshot unchanged.
- An exact read-only cloud-snapshot exporter and deterministic legacy reverse
  planner are implemented. The 33-app staged candidate round-tripped with all
  150 objects. Its plan against the 32-app legacy baseline contains one
  app/Search upsert, one numeric author-ID allocation, no media/screenshots or
  removals, and no catalog values or identities. Applying that plan remains
  unavailable until the guarded App Engine writer is implemented and rehearsed.
- A disabled Java catalog-archive validator independently checks normalized
  baseline/candidate archives and derives aggregate-only record changes, numeric
  allocation/absence checks, and screenshot Blobstore requirements. It has no
  route, legacy service adapters, entity mapper, or mutation method.
- A private live-state archive and token-free legacy rollback planner are
  implemented. The real isolated export reconciled five live states and 170
  protobuf bytes without exposing tokens or payloads in logs/reports. The plan
  preserves exact tokens/timestamps, requires absent-or-identical collision
  checks and atomic routing for all three state RPCs, and cannot apply writes.
- A matching disabled Java state-archive validator passes the complete App
  Engine test suite. It maps verified records into fresh in-memory legacy
  entities and performs aggregate-only absent/identical/expired collision
  preflight, but has no route or persistence operation. Production collision
  preflight and a writer-frozen replay remain intentionally unavailable.
- A guarded private capacity harness now replays only the exhaustive read corpus
  with per-response semantic comparison and provisional per-method latency
  gates. Its first real run passed 2,000 requests at concurrency 8 and 39.15
  requests per second with zero errors, 5xx responses, or differences. Cloud
  Monitoring independently counted the 2,016 measured-plus-warmup requests on
  one active instance with 1.97% mean CPU, 42.90% mean memory, and 3.94 ms mean
  in-container latency. The harness cannot send `uploadState`, and the evidence
  reports contain no payloads or credentials.
- The bounded private capacity ramp is complete at concurrency 8, 12, 16, and
  20: 15,000 measured requests and 1.301 GB of responses had zero transport,
  5xx, or compatibility failures. Concurrency 16 was the highest passing
  provisional latency step at 62.05 requests/second; concurrency 20 is retained
  as the first non-passing media latency boundary. Native telemetry stayed on
  one instance with CPU p95 at most 26%, memory p95 at most 45%, and in-container
  p95/p99 at most 12.1/17.72 ms, plus one 950.6 ms startup. Allocation metrics
  provide raw cost inputs. No service configuration or traffic changed.
- A checksum-validating private soak auditor now binds evidence to the checked-in
  `redirects1` revision and schema-3 four-surface boundary, verifies the revision
  still serves 100%
  of private traffic, and independently validates every retained comparison
  object and internal count. Job generation 4 requires 158 frozen API cases, 94
  live-discovered downloads, the 32-entry website list, and all six exact public
  redirects in every artifact. Its first execution passed all four surfaces and
  seeded the current clock at 03:55:01 UTC. The earlier schema-1 and schema-2
  artifacts remain valid historical evidence but cannot satisfy this exact
  revision and schema-3 gate.
  The first independently scheduled generation-4 execution then completed under
  the comparator service account at 04:18:28 UTC with 158/158 API cases and all
  three additional surfaces matching. The auditor checksum-validated all ten
  retained artifacts; two schema-3 reports now extend the current streak with a
  maximum observed gap of 1,406.73 seconds. The fourteen-day clock is current
  but not yet eligible. The baseline explicitly denies cutover, load-balancer,
  and catalog-activation authority.
- The promoted private `downloads1` revision received two additional guarded
  concurrency-8 API runs. Both matched 2,000/2,000 responses. The first retained
  a provisional `listAppsNano` latency non-pass caused by two client-path stalls
  in a 13-request sample while native revision metrics passed; the independent
  confirmation passed every latency gate at 38.08 requests/second. Neither run
  changed production routing or service configuration.
- The legacy public website's sole catalog dependency was isolated from the
  admin RPC family. `/rpc?m=pubapplist` is a public JSON read used by
  `apps.html`; the normalized mirror now exposes the same payload at the new
  unambiguous `/public/apps.json` path. A production-versus-archive comparison
  matched all 32 entries and every field with zero differences. The static
  candidate will change its fetch path, while all legacy admin RPCs remain on
  App Engine until the writer handoff.
- A create-only static-site builder now packages the current public pages,
  vendored browser dependencies, favicon, and graphics without deployment. It
  rewrites only the new JSON fetch and two legacy lightbox paths, removes two
  references to an absent unused script, and validates local asset closure. The
  route-complete build contains 78 objects/4,652,747 bytes with zero missing or
  unrouted assets, including real `/public/` compatibility aliases and a
  per-object checksum/content-type manifest. A 79-scenario live comparison
  matched every legacy source/status/content-type/CORS gate and all six expected
  HTML transformations. Static files, `/public/apps.json`, and the redirects are
  one validated `public_website` handoff group. The
  existing default Firebase Hosting site was confirmed to contain the separate
  TRS-80 KMP web application and is explicitly excluded; no new site or bucket
  was created.
- The immutable `website1` image
  (`sha256:3b6356d1d32d8eb6fbb4238ed682ad87e3684d7fb7dbe09e0f66a889f9b519f9`)
  was deployed at zero traffic and passed anonymous-denial, 32-entry website
  JSON, 94-download, 158-scenario API, and synthetic-state gates before private
  promotion. It served 100% of only the private candidate service until the
  additive `redirects1` revision passed its own zero-traffic gates.
- The scheduled comparator is upgraded without expanding IAM. It discovers the
  download corpus through public HTTP, is pinned to immutable image
  `sha256:22d135c40f50ec10649f9a8480ad9898dbceb52a6c2628cbad1f73ac93bed3d4`,
  and emits a schema-3 aggregate whose overall gate drives the existing alert.
  It now covers the API, downloads, website list, and public redirects. The
  checksum auditor still parses older artifacts as history but excludes them
  from the exact current soak.
- The immutable `redirects1` image was deployed at zero traffic and passed
  anonymous denial, API 158/158, downloads 94/94, website catalog 32/32,
  redirects 6/6, and the guarded synthetic state lifecycle before private
  promotion. It now serves 100% of only the private candidate. Its image is the
  same generation-4 comparator digest, IAM and resource limits are unchanged,
  and production/App Engine routing and the active catalog pointer did not move.
- The real published JVM, pinned TRS-80 KMP, and pinned embedded-C clients now
  also pass end to end against `redirects1` through an authenticated loopback
  proxy. The native gate discovers its media fixture through real catalog
  pagination, and the proxy-only JVM KMP adapter explicitly uses HTTP/1.1. Two
  failed diagnostic artifacts are retained from those harness corrections; the
  final token-free artifact passes all covered methods and synthetic states.

Open foundation work:

- Confirm the proposed `lb-next.retrostore.org`, `next.retrostore.org`, and
  `admin-next.retrostore.org` names and formally name the go/no-go owner and
  rollback operator. Sascha Ha is recorded only as the suggested owner pending
  confirmation. Provisioning the load balancer, DNS authorizations,
  certificates, public candidate services, or DNS records remains a separate
  explicitly approved action.
- Confirm the alert recipient and notification channel, attach it to the two
  installed policies, and explicitly enable them. Until then, the dashboard and
  logs provide evidence but do not page anyone.
- The `native-client-library` Arduino tree in this repository is an unfinished
  prototype: it sends a bodyless GET, ignores its configurable host, and has no
  media implementation. It is distinct from the working native C/ESP32 source
  in the reviewed TRS-80 repository and is not evidence for that deployed
  consumer. It needs an explicit retire-or-modernize decision.
- No production routing has changed, and no temporary migration version remains.

## Executive summary

RetroStore should move away from its monolithic App Engine application using a
compatibility-first, incremental migration. The agreed target is:

- A dedicated Python/Flask Cloud Run service for the existing public RetroStore
  API.
- A separate Python/Flask Cloud Run service that serves the admin HTML and owns
  the in-scope administrative operations.
- A server-rendered admin interface using Jinja, compiled Tailwind CSS, and
  optional htmx enhancements rather than a single-page application.
- Firebase Authentication for admin and publisher identities, exchanged for
  secure server-side session cookies.
- A new named Firestore Native database for normalized catalog metadata.
- A separate named Firestore Native database for ephemeral system states.
- Private Cloud Storage for Firebase buckets for media images, screenshots, and
  migration artifacts.
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
- Keep the RetroStore Card and TRS-IO hardware update subsystem unchanged on
  App Engine. `/card`, `/card/*`, `/trs-io`, and `/trs-io/*`, their legacy
  administration, and their Datastore entities are outside this migration.
  Any load-balancer URL map must keep these paths pinned to App Engine. Moving
  them requires a new, explicitly approved project; it is not a later phase of
  this plan.
- Expose the candidate services on separate hostnames and do not allow both
  admin applications to write production catalog data concurrently.
- Put a global external Application Load Balancer in front of App Engine and
  Cloud Run. Initially route production traffic 100% to App Engine, then move
  verified route groups through URL-map changes rather than further DNS changes.
- Require zero unexplained contract differences over the complete comparison
  corpus and the agreed soak period before a public API route can move.

## Goals

- Remove the runtime dependency on App Engine for the public RetroStore API,
  catalog administration, and other explicitly migrated surfaces while
  retaining the legacy hardware update route island.
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
- Reimplementing, exporting, importing, or modernizing the RetroStore Card or
  TRS-IO hardware update routes, administration, or stored images.
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
is a mandatory compatibility consumer, with the local canonical checkout at
`/Users/sascha/source/TRS-80`. Revision
`aecbddcc7f5515fb844bb7a1fc350d8ffaaf5ce5` is the currently reviewed pin. It
uses Wire-generated protobuf messages and exposes these calls to the shared
Android, iOS, and web application:

- `getApp`
- `listApps`
- `fetchMediaImages`
- `uploadState`
- `downloadState`

The same repository also contains an
[embedded C client](https://github.com/apuder/TRS-80/blob/master/app/src/main/c/retrostore/backend.cpp)
that sends legacy JSON requests to `getApp`, `listApps`, and
`fetchMediaImages`, then parses protobuf responses.

The KMP targets have distinct observable transports: Android uses
`HttpURLConnection`, iOS uses `NSURLSession`, and web uses a headerless browser
`fetch` simple request that depends on wildcard CORS without preflight. The
native C client uses plain HTTP on port 80 and labels its JSON as form data.
Those behaviors are contract inputs, not implementation details to clean up
during the server migration. The exact client sources and platform transports
are checksum-gated, and cutover requires end-to-end Android, iOS, and web runs
against both the candidate route and the production load balancer.

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
authentication, imports, and other in-scope admin concerns.

### Request routing

`retrostore.org` remains the stable public hostname. The eventual routing is:

| Path or surface | Target |
| --- | --- |
| Public static website | Dedicated Cloud Storage backend bucket, optionally CDN-cached |
| `/api/*` | `retrostore-api-compat` Flask service on Cloud Run |
| `/admin/*` | `retrostore-admin` Flask service on Cloud Run |
| `/assets/screenshots/*` | Stable RetroStore asset handler, optionally CDN-cached |
| `/card`, `/card/*`, `/trs-io`, `/trs-io/*` | Existing App Engine service; permanently excluded from this plan |
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
| 1 | Static website, its JSON dependency, and public redirects | Atomic after complete object/status/routing checks |
| 2 | Catalog reads | Canary gradually after zero-diff gates pass |
| 3 | Media reads and assets | Canary gradually after checksum/range parity |
| 4 | Admin and catalog writes | Atomic writer handoff; never dual-write |
| 5 | All three state endpoints | Move atomically after active-state migration |
| 6 | Other legacy routes | Keep on App Engine until each has a replacement and route-specific parity |

Catalog and media reads can use controlled traffic increments once their gates
pass. Admin writes cannot canary across two writers: freeze the old admin, run a
final sync, verify it, and enable the new admin as the sole writer. The three
state endpoints form one atomic route group so token allocation, upload, and
download never split across authorities.

The Card and TRS-IO paths are not in this sequence. They stay on App Engine
permanently under the approved scope. Unclassified routes also remain on App
Engine, so a missing route definition cannot expose an incomplete handler.

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
```

Mutations use POST followed by a redirect. Server-side validation rerenders the
form with entered values and field-level errors. Screenshot ordering must work
with accessible move-up and move-down controls; drag-and-drop can be an optional
enhancement.

Initial uploads should use ordinary multipart forms and stream through the admin
service to Cloud Storage. Signed or resumable direct uploads can be added later
if observed file sizes or request limits justify the extra coordination.

Legacy RPK import uses a two-request, preview-first form. The preview validates
one complete package in memory and retains no temporary server-side copy. Apply
requires the operator to choose the file again and compares its SHA-256 with the
preview before creating anything. Preserve a canonical package app UUID, reject
staged collisions instead of overwriting, and treat the package's publisher
name/email only as review information. The authenticated Firebase identity is
the authoritative owner. Bound the encoded package, aggregate decoded bytes,
disk count, screenshot count, individual assets, extensions, and image formats.
Upload immutable final assets before one atomic app/author/media/screenshot/audit
transaction, deleting every newly created object if validation, upload, or the
transaction fails. This workflow writes only the isolated top-level staging
collections; it never updates `catalogSnapshots` or the active pointer.

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
| `retrostore` | Durable catalog, users, and audit events |
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
states/{objectId}/{sha256}.pb
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
5. Export app metadata, authors, users, media relationships, active states, and
   Blobstore references. Do not export the hardware update entities.
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

- Every in-scope referenced binary is present and checksum-verified in Cloud
  Storage.
- Every in-scope durable entity has a normalized Firestore representation.
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
4. Implement app, author, media, screenshot, user, and import workflows against
   the new Firestore and Storage model.
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
2. Put the legacy catalog admin into read-only mode and run a final incremental
   sync, checksum reconciliation, and API comparison. Leave the hardware update
   administration unchanged.
3. Move the static website, `/public/apps.json`, and the six public redirects in
   one URL-map update; then move API catalog reads, then media reads/assets. Use
   controlled traffic increments where the load balancer supports safe canaries.
4. After those read groups are stable, enable the new admin as the sole catalog
   writer and permanently disable legacy catalog mutations.
5. Continue comparison against a frozen or safely refreshed legacy reference and
   monitor new catalog writes through the Flask API.
6. Migrate and verify every active state, briefly quiesce state writes if needed,
   and switch upload, download, and region endpoints atomically.
7. Keep `/card`, `/card/*`, `/trs-io`, and `/trs-io/*` routed to App Engine;
   they are not cutover candidates.
8. Preserve HTTP, HTTPS, CORS-simple POST, custom-domain behavior, legacy data,
   and reverse-sync capability throughout the observation window.

Routing rollback consists of returning the affected route group to App Engine in
the URL map. Data rollback must also restore a single writer: freeze the new
admin before re-enabling the legacy admin, reverse-sync any post-cutover catalog
changes, and reverse-sync new active states before returning the atomic state
group. No rollback relies on a destructive reverse migration.

Exit criteria:

- All in-scope public traffic is served by Cloud Run for the agreed observation
  period; the excluded hardware update routes remain on App Engine.
- Error rates and latency remain within agreed thresholds.
- Current KMP/JVM, web, C, and embedded JSON clients pass end-to-end production
  smoke tests.
- No unexpected writes occur in the legacy database.
- Routing and data rollback remain available until the observation window ends.

### Phase 6: Retire migrated App Engine surfaces

1. Confirm that only the explicitly excluded RetroStore Card and TRS-IO route
   groups and any dependencies they require remain on App Engine.
2. Keep those route groups pinned to App Engine in the production URL map.
3. Permanently disable only the superseded catalog administration and upload
   handlers; do not alter the hardware update handlers or administration.
4. Archive deployment configuration, normalized exports, and migration reports.
5. Retain legacy database and object backups for the agreed recovery period.
6. Keep the App Engine service operational for the hardware update subsystem.
   Full App Engine shutdown is incompatible with the approved scope and would
   require a separate decision and migration plan.
7. Delete legacy data only under a separate reviewed retention plan, explicitly
   excluding data still required by the hardware update subsystem.

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
- Audit-event creation for successful and rejected sensitive operations.

## Production go/no-go gates

"100% sure" means that all agreed evidence is green and no known high-severity
issue remains; it does not mean relying on an uneventful small canary. Before
the first production backend route moves from App Engine, require:

- 100% of expected in-scope durable entities and active states are accounted
  for.
- Every in-scope referenced object exists with matching size and checksum, with
  zero broken or orphaned references outside a reviewed cleanup list.
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

- The public static website bucket's CDN, cache-invalidation, and deployment
  policy. It must remain separate from the private application-assets bucket.
  A non-executable proposal now uses a fresh empty bucket per release, atomic
  backend switching, CDN disabled, and `Cache-Control: no-store` for the initial
  handoff; this still needs confirmation before bucket or IAM creation.
- The retention period for normalized migration exports and legacy backups.
- Whether application reports continue through email, become the recommended
  isolated private admin queue, or are explicitly retired. The current
  contract, safe live probes, PII boundary, and least-privilege options are in
  [the public report migration note](public-report-migration.md). A queue also
  needs an approved retention period; email needs confirmed recipients and
  sender policy.
- Approval or revision of the proposed legacy-user policy: preserve all ten as
  non-authorizing historical profiles, retain the one matched administrator,
  and manually review rather than automatically invite the other two legacy
  administrators.
- Confirmation of the proposed `lb-next.retrostore.org`,
  `next.retrostore.org`, and `admin-next.retrostore.org` hostnames.
- Confirmation or revision of the checked-in fourteen-day zero-diff soak.
- Confirmation or revision of the checked-in 1%, 5%, 25%, 50%, and 100% read
  canaries, 24-hour minimum step observation, and automatic rollback
  thresholds.
- Who has go/no-go authority for each route group and who operates rollback.

These decisions do not block contract capture, the Python project skeleton, or
the read-only infrastructure inventory.

Plain HTTP is no longer a migration decision: the reviewed native clients use
raw port 80, so the in-place replacement must preserve it without an HTTPS
redirect. Any deprecation belongs to a later, separately approved client
migration after all deployed native consumers are proven upgraded. A safe live
probe also confirmed the current port-80 `listApps` request returns HTTP 200 and
716 protobuf bytes with no redirect.

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
- [x] Pin and checksum-audit the canonical TRS-80 application revision,
  including its shared protobuf/client wiring and Android, iOS, web, and native
  C transports; compile all three KMP targets and execute its KMP/native clients
  against the local candidate.
- [x] Run the expanded suite against the local Flask candidate with zero
  differences across all 45 reviewed scenarios.
- [x] Produce the route and read-only cloud infrastructure inventory.
- [x] Build a repeatable read-only exporter/reconciler for representative
  Objectify encodings, binary sizes and checksums, and reference integrity.
- [x] Implement, test, and deploy the sanitized App Engine-side
  Blobstore-content and live Search-index inventory operation without promotion.
- [x] Capture and reconcile two matching reports from the reviewed,
  non-promoted App Engine version, then delete all temporary versions.
- [x] Classify the eight unreferenced Blobstore objects in a protected artifact,
  bind their metadata to the complete byte-verification report, and prove each
  duplicate byte sequence is preserved in the normalized catalog archive.
- [x] Reconcile legacy users, app attribution, Firebase identities, and modern
  roles in a protected read-only artifact; emit an identity-free no-write policy
  plan for explicit approval.
- [x] Implement the legacy `/downloadapp` read route from the normalized mirror
  and exhaustively prove every current ZIP entry and typed media response
  against App Engine without routing traffic.
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
- [x] Deploy the private Cloud Run compatibility candidate and run both the
  158-scenario read-only corpus and guarded synthetic state lifecycle through
  its external URL with the keyless runtime identity. Restore and verify private
  invocation after the temporary public diagnostic.
- [x] Deploy the private server-rendered admin candidate with Google-only
  Firebase Authentication, hardened session/CSRF boundaries, compiled Tailwind,
  and read-only synchronized catalog inventory and detail pages.
- [x] Add the isolated staged app and author create/edit/delete lifecycle with
  publisher ownership, optimistic revisions, explicit deletion confirmation,
  and atomic audit events.
- [x] Add isolated, private staged media-slot and ordered-screenshot workflows
  with bounded uploads, checksum-addressed objects, replacement/deletion cleanup,
  optimistic revisions, ownership enforcement, and atomic audit events.
- [x] Exercise the complete staged app/media/screenshot lifecycle through the
  authenticated live browser, reconcile the intermediate and deleted Firestore,
  Storage, revision, and audit states, and re-run the 158-scenario public API
  comparison with zero differences.
- [x] Implement the preview-first, SHA-bound legacy RPK importer against only
  the isolated future schema, with exact-ID preservation, authenticated
  ownership, bounded whole-package validation, atomic metadata/audit, immutable
  objects, collision refusal, and failure cleanup.
- [x] Deploy and exercise one disposable RPK through the authenticated private
  admin, reconcile its staged metadata/assets/audit record and cleanup, then
  repeat the public 158-scenario comparison with zero differences.
- [x] Implement the deterministic active-snapshot-to-working-catalog bridge,
  source fingerprints, atomic control/audit record, legacy-ID support, and
  service/UI read-only guards. Keep the operation private and leave the active
  public snapshot unchanged.
- [x] Deploy the read-only guard, run the real archive dry run, materialize the
  live working set through the dedicated migrator, reconcile it, and repeat the
  158-scenario public comparison without changing the active snapshot.
- [x] Implement and exercise a stage-only publication rehearsal that rebuilds
  the active snapshot from the materialized working collections, verifies all
  metadata and objects, and has no activation capability.
- [x] Build and privately deploy an immutable staged publication candidate,
  pin it to a separate preview service, prove all pre-existing API behavior and
  isolated state RPCs, and leave the active pointer unchanged.
- [x] Add copy-on-write published app metadata and asset drafts with guarded
  publication merging, separate draft collections, object ownership, optimistic
  revisions, audit events, and a private server-rendered admin deployment.
- [x] Freeze the proposed candidate hostnames, App Engine-only initial URL map,
  exact API route groups, permanent hardware route exclusion, monitoring
  thresholds, soak policy, and rollback invariants in a CI-validated
  machine-readable front-door plan.
- [x] Deploy privacy-safe structured request events and a least-privilege,
  read-only hourly comparator job that retains immutable full-corpus reports.
- [x] Add and exercise a guarded private read-load harness with semantic
  comparison, per-method latency gates, and exact-revision Cloud Run resource
  evidence without exposing payloads, tokens, or catalog values.
- [x] Run and summarize a bounded private capacity ramp through its first
  non-passing latency step, including startup and raw allocation/cost metrics,
  without changing the serving revision or traffic.
- [x] Add a generation- and checksum-validating retained-evidence auditor with a
  revision-bound private zero-diff clock and explicit no-cutover baseline.
- [x] Audit the anonymous `/reportapp` form and validation contract without
  triggering email, document its PII and abuse boundary, and keep it on App
  Engine until queue/email/retirement and retention choices are explicit.
- [x] Preserve the six exact public website redirects in Flask, compare their
  empty-body 302 status and destinations without following them, and add them
  to the fail-closed candidate route plan and retained evidence schema.
- [x] Close the complete public static route set, preserve the legacy `/public/`
  aliases, generate per-object deployment metadata, and compare all 78 objects
  plus `/` with zero differences outside six deterministic HTML changes.
- [x] Make the one intentional static/dynamic route overlap machine-readable:
  exact `/public/apps.json` wins over the `/public/` static alias, both remain
  in one atomic handoff group, and validation rejects every undeclared overlap.
- [x] Add a local-only static deployment planner that checksum-verifies all 78
  objects, rejects every known existing project bucket, emits only
  create-if-absent uploads and zero deletes, and deliberately has no apply path.
- [x] Bind plain HTTP port 80 pass-through into the validated migration contract
  because both reviewed native client trees still require it; an HTTPS-only
  policy is explicitly deferred to a separate future client migration.
- [x] Run the revision- and checksum-pinned JVM, TRS-80 KMP, and embedded-C
  clients through an authenticated loopback proxy to the current private
  revision, including isolated synthetic state lifecycles and native pagination.
- [ ] Confirm the proposed hostnames and formally name the go/no-go and rollback
  owners before any load-balancer, certificate, public IAM, or DNS resource is
  created. Current DNS, certificates, HTTP behavior, and absence of an existing
  load balancer are documented and reverified.

The unfinished Arduino tree in this repository is not the reviewed native
C/ESP32 consumer and remains outside the compatibility gate; leave it untouched
unless it receives a separately scoped repair. The compatibility API's first
deployed Phase 2 gate and the admin's first read-only slice are complete. The
initial Google sign-in, explicit administrator claim, server-session exchange,
and browser inventory review have passed through the private Cloud Run proxy.
Administrator/publisher role management is atomically audited in Firestore, and
the isolated staging app/author create/edit/delete workflow is deployed. The
isolated media-slot, ordered-screenshot, and guarded RPK import workflows are
also deployed and have passed complete authenticated lifecycle proofs. The
working-set-to-immutable-snapshot publication boundary, separate pinned preview,
guarded activation/rollback command, and copy-on-write draft UI are now deployed
privately without activation. Front-door preparation, request observability, the
private comparator, its dashboard, the first private capacity gate, the
stage-only half of repeatable mirror synchronization, and the read-only
reverse-sync planner are complete. While hostname and owner confirmation remain
pending, the revision-bound private soak continues to accumulate automatically.
The remaining data-policy choice now has a read-only evidence-backed proposal:
retain all ten historical profiles without granting access and manually review
the two unmatched legacy administrators. Actual
legacy reverse writes and load-balancer provisioning still require explicit
operator gates and remain unavailable.
Synchronized-catalog activation remains disabled.
The RetroStore Card and TRS-IO hardware update subsystem stays unchanged on App
Engine and is not part of that work queue.

No production routing or legacy data should change during this milestone.

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

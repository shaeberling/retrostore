# RetroStore current-system inventory

Status: Infrastructure, Datastore, Blobstore, and Search validation complete

Last verified: 2026-08-10

This document records observed production and source behavior. Unknown values
remain explicit; no production resources were created or modified while
collecting it.

## Local cloud context

- gcloud project: `trs-80`
- gcloud account selected: `saschah@gmail.com`
- Firebase default project in this repository: `trs-80`
- Firebase project number: `760396810462`
- Firebase project state: `ACTIVE`
- App Engine application ID: `trs-80`

The selected gcloud account was reauthenticated and the project was verified
before this inventory. Initial cloud discovery was read-only. Controlled,
non-promoted App Engine versions were later deployed and deleted to collect the
bundled-service evidence described below. On 2026-08-07, the approved isolated
Firestore databases and private Storage buckets described below were created.
They now contain only the imported immutable catalog mirror, isolated staging
and administration records, and synthetic state-test data described below. No
legacy resource, production data, production IAM binding, or route was changed.

## Firebase and Firestore

Observed with `firebase firestore:databases:list --project trs-80`:

| Database ID | Mode | Location | Concurrency | Delete protection | Purpose |
| --- | --- | --- | --- | --- | --- |
| `(default)` | Datastore | `nam5` | Optimistic | Disabled | Legacy App Engine/Objectify production data |
| `retrostore` | Firestore Native, Standard | `nam5` | Pessimistic | Enabled | Durable migration mirror and isolated administration data |
| `retrostore-state` | Firestore Native, Standard | `nam5` | Pessimistic | Disabled | Ephemeral synthetic state target |

The two named databases were created on 2026-08-07 after topology approval.
`retrostore-state` has a TTL policy on `states.expiresAt`. The migration must
leave `(default)` unchanged and authoritative throughout the parallel run and
rollback window.

Observed Firebase resources:

- Default Hosting site: `trs-80`, served at `https://trs-80.web.app`.
  Its live channel currently contains the separately deployed TRS-80 KMP web
  application (24 files in the 2026-08-06 release), so the RetroStore static
  bundle must not reuse this site.
- Registered Firebase apps include the Android app named `TRS-80 Android`,
  namespace `org.puder.trs80`, and the web app used by the new administration
  candidate.
- Firebase Authentication is initialized with Google sign-in for the new admin
  candidate. Authorization still comes from server-verified sessions and
  Firestore role profiles; the browser never receives direct database access.

## App Engine deployment

| Property | Current value |
| --- | --- |
| Application location | `us-central` |
| Database integration | Cloud Datastore compatibility |
| Default hostname | `trs-80.uc.r.appspot.com` |
| Default service account | `trs-80@appspot.gserviceaccount.com` |
| Serving status | `SERVING` |
| Services | One: `default` |
| Deployed versions | 15 |
| Live version | `20230819t145020` |
| Live runtime | Java 11, standard environment, F1 |
| Traffic | 100% to the live version |

Fourteen older versions are Java 8 deployments from 2022, receive no traffic,
and remain in `SERVING` state. Three temporary Java 25 inventory versions were
deployed without promotion on 2026-08-06 and deleted after successful
validation. Java 25 version `migration-export-20260807-1312` was deployed
without promotion on 2026-08-07 for the controlled catalog export, then deleted
after the authenticated archive passed independent local verification. The live
version was deployed on 2023-08-19 and has App Engine bundled APIs enabled. A
single dynamic instance was observed during the initial inventory; instance
counts and traffic metrics are transient and are not migration capacity
targets.

The App Engine application currently owns the production custom-domain front
door directly:

- `retrostore.org` maps to App Engine with four Google frontend IPv4 addresses
  and four IPv6 addresses.
- `www.retrostore.org` is a CNAME to `ghs.googlehosted.com`.
- Both mappings have App Engine-managed certificates.
- The apex certificate observed on 2026-08-05 is issued by Google Trust Services
  and is valid through 2026-09-15.
- Authoritative DNS uses `ns-cloud-b1` through `ns-cloud-b4.googledomains.com`.
- There is no Cloud DNS managed zone in project `trs-80`.
- There are no Compute URL maps, forwarding rules, reserved addresses, backend
  services, network endpoint groups, or Compute-managed certificates.

This confirms that production traffic goes directly to the App Engine domain
mapping today; there is no existing external Application Load Balancer to
modify in place.

## App Engine runtime and dispatch

Production traffic runs a Java 11 WAR using the App Engine bundled services.
The source is configured to stage new versions on Java 25 with EE 8
compatibility while retaining Java 11 bytecode, Servlet 2.5, and
`javax.servlet`. `MainServlet` handles both GET and POST through one
priority-ordered request chain. `ObjectifyFilter` wraps all paths.

The source dispatch order is significant:

1. Favicon resources.
2. `/ping` cron keep-alive.
3. Exact public redirects.
4. Public website resources.
5. App report form and mail submission.
6. App/media downloads.
7. Public RetroStore Card and TRS-IO firmware calls.
8. Login gate for paths that are not public or whitelisted.
9. Admin bootstrap, firmware admin, import, and `/rpc` operations.
10. Screenshot serving and upload operations.
11. Polymer and other static admin resources.
12. Post-upload handlers.
13. Public `/api/*` compatibility calls.
14. `/updateData` search-index refresh.

## Public and legacy route families

| Route family | Current purpose | Migration disposition |
| --- | --- | --- |
| `/` and public files such as `/apps.html` | Static public website | Static route group |
| `/community[/]` | Redirect to Discord | Preserve redirect |
| `/rsc[/]` | Redirect to RetroStore Card GitHub | Preserve redirect |
| `/app[/]` | Redirect to the Google Play app | Preserve redirect |
| `/api/<method>` | Public compatibility API | Flask compatibility service |
| `/downloadapp?appId=...&type=...` | Raw media or generated ZIP download | Compatibility service |
| `/rpc?m=pubapplist` | Public JSON catalog used only by the legacy static website | Replaced in the new static bundle by parity-tested `/public/apps.json`; other `/rpc` methods remain admin-only |
| `/screenshotServe?key=...` | Login-protected Polymer-admin screenshot preview | Retire with the legacy admin; public clients receive direct serving URLs from `/api/*` |
| `/reportapp` | Public report form and Mail-service submission | Rebuild or explicitly retire after review |
| `/card/{revision}/version` | RetroStore Card firmware version | Remain unchanged on App Engine; excluded from current migration |
| `/card/{revision}/firmware` | RetroStore Card firmware bytes | Remain unchanged on App Engine; excluded from current migration |
| `/trs-io/{revision}/version` | TRS-IO firmware version | Remain unchanged on App Engine; excluded from current migration |
| `/trs-io/{revision}/firmware` | TRS-IO firmware bytes | Remain unchanged on App Engine; excluded from current migration |
| `/card`, `/trs-io` | Authenticated firmware admin | Remain unchanged on App Engine; excluded from current migration |
| `/rpc?m=<method>` | Polymer admin RPC surface | Replace with server-rendered admin forms |
| `/post/uploadDiskImage` | Admin media upload | New Flask admin upload |
| `/screenshotUpload*`, `/screenshotUrlForUpload*` | Blobstore screenshot upload | New Flask admin upload |
| `/import*` | Authenticated RPK import | New Flask admin workflow |
| `/updateData` | Search-index refresh | Removed after search migration |
| `/ping` | One-minute App Engine warmup cron | Retain unless independently proven unnecessary for the surviving hardware routes |

The legacy `/rpc` registry contains:

- `userlist`, `getSiteContext`, `addEditUser`, and `deleteUser`.
- `addEditApp`, `getAppFormData`, `applist`, `pubapplist`, and `deleteApp`.
  `pubapplist` is the one public read method; the others are authenticated admin
  operations.
- `listDiskImages`, `deleteDiskImage`, and `uploadDiskImage`.
- `listScreenshots`, `deleteScreenshot`, and `reorderScreenshots`.

## Public API methods

The frozen API 0.2.13 surface is:

| Method | Request | Response | Legacy JSON |
| --- | --- | --- | --- |
| `getApp` | `GetAppParams` | `ApiResponseApps` | Yes |
| `listApps` | `ListAppsParams` | `ApiResponseApps` | Yes |
| `listAppsNano` | `ListAppsParams` | `ApiResponseAppsNano` | No |
| `fetchMediaImages` | `FetchMediaImagesParams` | `ApiResponseMediaImages` | Yes |
| `fetchMediaImageRefs` | `FetchMediaImageRefsParams` | `ApiResponseMediaImageRefs` | No |
| `fetchMediaImageRegion` | `FetchMediaImageRegionParams` | Raw bytes | No |
| `uploadState` | `UploadSystemStateParams` | `ApiResponseUploadSystemState` | No |
| `downloadState` | `DownloadSystemStateParams` | `ApiResponseDownloadSystemState` | No |
| `downloadStateMemoryRegion` | `DownloadSystemStateMemoryRegionParams` | Raw bytes | No |

The canonical schema is vendored at `backend/proto/ApiProtos.proto`, with its
exact revision and checksums in `backend/proto/UPSTREAM.md`.

### Observed live transport behavior

Mutation-safe probes against `retrostore.org` on 2026-08-05 and 2026-08-06
establish:

- Headerless POST requests are accepted.
- GET and HEAD reach API methods as well as POST.
- Successful and semantic-error method responses use HTTP 200,
  `application/octet-stream`, and `Access-Control-Allow-Origin: *`.
- Unknown methods use HTTP 400, `text/plain;charset=iso-8859-1`, and the exact
  body `RPC method '<name>' not found.` without the CORS response header.
- Plain HTTP remains reachable and produces the same unknown-method response
  when a request body length is supplied.
- OPTIONS returns HTTP 200 and advertises `GET, HEAD, POST, TRACE, OPTIONS`, but
  the observed response does not include an allow-origin header.
- Raw-region errors return an empty `application/octet-stream` body with HTTP
  200 and the wildcard allow-origin header.
- Four invalid-input paths currently return HTTP 500, `text/html`, and no CORS
  header: negative `listApps.start`, a well-formed media token naming a missing
  file, malformed `fetchMediaImages`, and malformed `fetchMediaImageRefs`.

The reviewed golden baseline has 45 scenarios: 12 established baselines, 9
successful reads, 15 boundary cases, and malformed protobuf for all 9 methods.
It freezes catalog ordering, protobuf and legacy JSON success behavior, media
selection and placeholders, binary hashes, raw prefix/tail/EOF reads, missing
state behavior, and the four HTTP 500 cases above. Two independent complete
captures matched with zero differences. It is stored in
`backend/tests/contract/golden/live-safe-baseline.json`.

Important legacy edge case: an empty `uploadState` message has no memory
regions, passes `allMatch`, and allocates a token. Contract probes must never use
an empty upload. The corpus checks both a negative-start region and malformed
protobuf, and its safety guard refuses to run any write scenario that could
reach state storage.

## Datastore, Blobstore, and bundled-service data

Objectify registers exactly seven entity kinds:

| Kind | Count | ID | Binary or relationship notes |
| --- | ---: | --- | --- |
| `AppStoreItem` | 32 | UUID string | Nested listing; four disk IDs; cassette, command, and BASIC IDs; ordered Blobstore screenshot keys |
| `Author` | 22 | Numeric | Indexed name |
| `MediaImage` | 60 | Numeric | App ID, filename, description, upload time, and inline bytes |
| `RetroCardFirmware` | 9 | `<revision>-<version>` | Inline firmware bytes |
| `TrsIoFirmware` | 5 | `<revision>-<version>` | Inline firmware bytes |
| `RetroStoreUser` | 10 | Email | Names and account type |
| `SystemState` | 391 | Token `100`–`999` | Registers, memory-region byte arrays, indexed creation timestamp |

The seven application kinds contain 529 entities total. A read-only aggregate
using the legacy seven-day validity rule found 4 active `SystemState` entities
on 2026-08-05. The other state entities are expired but remain stored until
their tokens are reused.

Datastore has two ready composite indexes, one each for `RetroCardFirmware` and
`TrsIoFirmware`, ordered by ascending revision and descending version.

Legacy Blobstore metadata contains 98 objects totaling 6,094,655 bytes (about
5.8 MiB); the largest object is 994,809 bytes. This storage is separate from the
three visible Cloud Storage buckets and is represented by the Datastore system
kind `__BlobInfo__`.

The repeatable sanitized inventory scanned all 627 application and Blobstore
metadata records and measured the inline binary fields:

| Kind and property | Values | Total bytes | Largest value |
| --- | ---: | ---: | ---: |
| `MediaImage.data` | 60 | 6,826,237 | 256,016 |
| `RetroCardFirmware.data` | 9 | 4,889,680 | 777,424 |
| `TrsIoFirmware.data` | 5 | 3,898,752 | 779,984 |
| `SystemState.memoryRegions[].data` | 1,085 | 23,168,623 | 65,536 |

Every current durable relationship resolves correctly:

- All 32 app-to-author references resolve; 4 author records are unreferenced.
- All 32 publisher references resolve to the 10 legacy user records.
- All 60 media slots resolve to exactly 60 media entities, with no orphaned
  media, missing parent apps, or ownership mismatches.
- All 90 distinct screenshot references resolve to Blobstore metadata.
- Eight additional Blobstore objects are unreferenced. They were conservatively
  retained for separate protected classification rather than deleted.

The live encodings also establish importer defaults that are not obvious from
the Java field declarations:

- `trs80Extension.basic` is absent on 11 of 32 apps and must decode as zero.
- `SystemState.memoryRegions` is absent on 16 of 391 states and must decode as
  an empty list.
- Twelve states have a null model.
- All 60 current media descriptions are stored as null.

The inventory command emits aggregate SHA-256 values for every non-user entity
kind and binary property, while deliberately suppressing a user-record content
digest. Two consecutive production runs produced the same canonicalized report
hash after excluding `generated_at`:
`c58a69bd9573424546ba01f8f62d2b08bc1daf14ba64a4addecd789efb6c753f`.
This is the sanitized 2026-08-05 baseline; it establishes stability during the
observation window but is not a cross-kind transactional snapshot. The command
and its usage are documented in `backend/README.md`.

The source names the App Engine Search index `AppStoreItem`. It indexes app name
and description with the app ID as document ID. `refreshIndex` writes all
current apps but does not delete stale documents. The production-only inventory
found exactly 32 live documents matching all 32 source app entities, with no
missing, stale, duplicate-ID, missing-ID, or content-mismatched documents. Both
captures produced matching live and expected aggregate SHA-256
`e89144f61f87285b4b89fd2f718c2891c2aebfc25b213e3ad37f3c7fb4cf46c1`.
Java 25 does not expose Search storage usage/limit, so those optional metrics
remain explicitly unavailable.

The same captures read and hashed all 98 Blobstore objects. Every content MD5
matched its metadata, and the stable aggregate content SHA-256 is
`dbeb8d33efcb59ddb28e341f483429e7d81b7452a82d1cce50d6f3dee6946aeb`.
After excluding `generated_at`, both complete reports have normalized SHA-256
`7ba290376c6641c511c7cd58b4b1a7c745d7ba2780d425903de69da84de4fb71`.

Other stateful dependencies:

- Blobstore holds screenshots; app entities retain ordered Blobstore keys.
- App Engine Images produces serving URLs for Blobstore screenshots.
- App Engine Search indexes catalog data.
- Memcache caches catalog reads, resources, image URLs, and available state
  tokens. State allocation is therefore not currently concurrency-safe across a
  cache miss/race.
- App Engine Users authenticates admin and publisher accounts.
- App Engine Mail sends app reports.

System-state tokens are logically reusable after seven days, although expired
entities remain in Datastore until overwritten.

## Cloud Storage and container infrastructure

All five buckets use the `US` multi-region and Standard storage. Durable data
keeps seven-day soft-delete recovery; the ephemeral state bucket disables soft
delete so its lifecycle does not retain expired payloads for an extra week:

| Bucket | Objects | Stored bytes | Purpose and notable policy |
| --- | ---: | ---: | --- |
| `trs-80.appspot.com` | 0 | 0 | Firebase/App Engine default bucket; no lifecycle rule |
| `staging.trs-80.appspot.com` | 0 | 0 | App Engine staging; delete objects after 15 days |
| `us.artifacts.trs-80.appspot.com` | 92 | About 1.35 GiB | Legacy Container Registry artifacts |
| `trs-80-retrostore-assets` | 150 baseline objects | 12,738,856 baseline bytes | Private durable mirror; uniform access, public-access prevention, seven-day soft delete |
| `trs-80-retrostore-state` | Synthetic smoke-test objects only | Ephemeral | Private state target; uniform access, public-access prevention, delete after eight days, soft delete disabled |

The three legacy buckets retain their existing ACL configuration. Uniform
bucket-level access and public-access prevention are enforced on both new
buckets; object versioning is disabled. Additive database- and bucket-scoped IAM
grants exist for dedicated migrator, API, and admin service accounts. No
service-account key was created.

Artifact Registry now contains the dedicated `retrostore` repository and Cloud
Build is enabled. Three unrouted private Cloud Run services exist in
`us-central1`: the active-snapshot API candidate, the pinned staged-snapshot API
preview, and the administration candidate. Each denies anonymous invocation;
none is connected to `retrostore.org`.

A private `retrostore-hourly-comparator` Cloud Run Job uses a fourth dedicated
keyless identity. It can invoke only the private active-snapshot API candidate
and create new objects only under the conditional
`operations/comparisons/` assets-bucket prefix; it has no database, state,
asset-read, overwrite, or delete permission. Its first 158-scenario execution
passed and retained a checksum-verified report. Cloud Scheduler is enabled with
an hourly UTC trigger. The assets bucket now deletes only comparison-report
objects after 90 days; application asset paths are not lifecycle targets.
The scheduler-triggered execution also passed 158/158, proving the authenticated
delivery path. A migration dashboard and successful-comparison log metric now
exist. Difference and 90-minute stale-evidence alert policies are installed but
deliberately disabled without notification channels pending assignment of the
responsible recipient.

The private API candidate also has a guarded read-only capacity harness. Its
first 60-second/2,000-request run on 2026-08-10 exercised the full 158-scenario
corpus at concurrency 8 and completed at 39.15 requests per second with every
response HTTP 200, zero semantic differences, and all provisional per-method
p95/p99 gates passing. Native metrics counted exactly 2,016 requests including
warmup, one active instance, 1.97% mean CPU, 42.90% mean memory, and 3.94 ms mean
in-container latency. The harness cannot send `uploadState` and its reports do
not contain payloads or credentials.

The completed private ramp then covered 15,000 measured requests and 1.301 GB
of responses at concurrency 8/12/16/20. Contract integrity remained perfect at
every step. Concurrency 16 was the highest passing provisional latency step at
62.05 requests per second; concurrency 20 was the first non-passing boundary
because of two media latency gates, despite remaining on one instance with CPU
p95 no higher than 26%, memory p95 no higher than 45%, and in-container p95/p99
no higher than 12.1/17.72 ms. One startup measured 950.6 ms. The accepted
concurrency-16 step recorded 54.4 billable instance/CPU seconds and 27.2
GiB-seconds of memory allocation. No service setting or traffic changed.

A separate read-only soak auditor now verifies the retained comparison object
paths, generations, content digests, schemas, counts, URLs, and approval gates,
then confirms the expected Cloud Run revision still serves 100% of private
traffic. The checked-in boundary now starts after `website1` became ready at
100% private traffic. The latest run validated seven retained zero-diff reports;
the scheduled and manual runs after the new boundary both matched 158/158 with
no approvals and start the clock at 2026-08-10 03:18:41 UTC. The private 14-day
clock is current but not yet eligible. The earlier five reports remain valid
evidence for prior revisions.

The pre-existing App Engine, Compute, and Firebase Admin SDK identities remain.
The migration adds separate keyless migrator, public API, and administration
identities with scoped access to the named databases, private buckets, and
private candidate services. It does not grant them access to rewrite the legacy
default database.

## Remaining data-migration work

Infrastructure discovery and Datastore, Blobstore, and Search reconciliation are
complete enough to choose the target topology. Remaining data work is:

- Decide whether the remaining legacy `RetroStoreUser` records become invited
  Firebase identities, disabled historical records, or both. The new Firebase
  administrator role store is deliberately separate from those legacy records.

The eight unreferenced Blobstore objects were classified read-only on
2026-08-10. The protected mode-0600 artifact reconciles 32 apps, 90 distinct
screenshot references, and all 98 Blobstore metadata rows. The eight objects
are seven PNG files and one JPEG totaling 182,036 bytes. Every object has size,
MD5, filename, and creation metadata, and every size+MD5 pair matches exactly
one referenced screenshot. The earlier bounded App Engine scan independently
proved that all 98 metadata MD5 values match the bytes. Finally, the classifier
recomputed MD5 from the matching objects in the retained normalized catalog ZIP
and verified all eight byte sequences are present there. The archive remains
8,418,142 bytes with SHA-256
`3bf584091e59bd5200bc36c8178aa9923148e8999eae0238f5577a5ade4fcefa`.
No additional content copy is needed to preserve them, although the protected
key-to-screenshot mapping is retained for audit. No legacy object was changed,
fetched again, or deleted.

The remaining user decision now has protected read-only evidence. The 10 legacy
records are 3 `ADMIN` and 7 `NO_ACCOUNT`; all seven `NO_ACCOUNT` records provide
attribution for current apps and grant no legacy access. One legacy administrator
matches the only Firebase identity and its verified `administrator` role. The
two other legacy administrators have no Firebase identity and publish no current
app. The proposed policy preserves all 10 as non-authorizing historical profiles,
keeps the existing administrator unchanged, never creates accounts for
attribution-only records, and sends the other two administrators to manual
review. The identity-free planner has no Firebase, Firestore, or role mutation
path. See `docs/legacy-user-migration.md`; no policy has been applied.

The approved target locations are `nam5` for both named Firestore databases,
`US` for the two private buckets, and `us-central1` for Cloud Run. The immutable
32-app production mirror, its materialized read-only working collections, one
isolated staged app, and synthetic state probes have been reconciled. The
legacy stores remain authoritative and unchanged.

A separate recurring catalog-refresh boundary now consumes any later normalized
full export, reports deterministic ID-only changes against a baseline, and can
stage only a checksum-verified immutable snapshot. Apply requires the exact
current active snapshot as a precondition and proves the active mirror is
unchanged afterward; the command has no activation path. The first real-cloud
rehearsal reused all 150 objects from the 32-app baseline, reported zero changes,
and left `catalog-ec07d9d7c8d47c8a46b745fc82b8d7f231e905dc6b6f7e00f4375547cf303de8`
active.

The inverse read boundary can export one exact staged/ready cloud snapshot as a
create-only normalized archive and independently round-trip it. The real staged
33-app candidate exported with the expected `5b0bbf8b...` identity while
retaining the same 150 checksum-verified objects and 12,738,856 bytes. A
read-only legacy reverse planner compared it with the 32-app baseline and found
exactly one app/Search upsert, no media or screenshot operations, no removals,
and one required legacy numeric author-ID allocation. The deterministic plan
has no apply path; no legacy entity, Blobstore object, Search document, route,
or active cloud pointer changed.

A disabled Java catalog validator now independently parses the normalized
baseline/candidate format, verifies all enums, slots, references, objects,
checksums, and reconciliation data, and derives aggregate-only legacy mutation
and allocation requirements. Its test candidate exercises app, author, media,
screenshot, and Search-dependent work. It has no route, Objectify, Blobstore,
Search, allocation, entity-mapping, or apply operation.

State continuity now has a separate private archive format and token-free
rollback plan. A read-only real-cloud export found five logically live isolated
states totaling 170 protobuf bytes, validated their Firestore records and exact
Cloud Storage generations/checksums, and wrote the token-bearing payload archive
with mode `0600`. The public report contains no tokens or payloads. The legacy
plan maps those records directly to embedded Objectify `SystemState` entities,
requires absent-or-identical token preflight and atomic routing of all three
state RPCs, and has no apply path. No legacy state was written.

The legacy App Engine code now has a matching disabled archive validator. The
full Java suite proves cross-language parsing, checksum/aggregate validation,
live-window enforcement, protobuf validation, and in-memory conversion of exact
tokens, creation timestamps, models, registers, and memory regions. The class is
not registered in `MainServlet` and has no Objectify or other mutation method.
Its read-only collision preflight classifies absent, exactly identical, and
expired legacy records while rejecting a different live record without logging
the token. It has not been run against frozen production legacy state data.

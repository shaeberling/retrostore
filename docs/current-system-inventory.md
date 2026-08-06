# RetroStore current-system inventory

Status: Infrastructure, Datastore, Blobstore, and Search validation complete

Last verified: 2026-08-06

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
before this inventory. Initial cloud discovery was read-only. Three controlled,
non-promoted App Engine versions were later deployed and deleted to collect the
bundled-service evidence described below. No APIs, production data, IAM
bindings, or routes were changed.

## Firebase and Firestore

Observed with `firebase firestore:databases:list --project trs-80`:

| Property | Current value |
| --- | --- |
| Database ID | `(default)` |
| Database type | `DATASTORE_MODE` |
| Location | `nam5` |
| App Engine integration | `ENABLED` |
| Edition | `STANDARD` |
| Concurrency mode | `OPTIMISTIC` |
| Delete protection | `DISABLED` |
| Point-in-time recovery | `DISABLED` |

There are no named Firestore Native databases yet. The migration must leave
`(default)` in Datastore mode and create new named databases only after the App
Engine and bucket locations are confirmed.

Observed Firebase resources:

- Default Hosting site: `trs-80`, served at `https://trs-80.web.app`.
- Registered Firebase apps: one Android app named `TRS-80 Android`, namespace
  `org.puder.trs80`.
- No Firebase web app is currently registered.
- Firebase Authentication is not initialized. The Identity Toolkit project
  configuration endpoint returns `CONFIGURATION_NOT_FOUND`, so there are no
  existing provider settings to preserve or Firebase identities to reconcile.

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
validation. The live version was deployed on 2023-08-19 and has App Engine
bundled APIs enabled. A single dynamic instance was observed during the initial
inventory; instance counts and traffic metrics are transient and are not
migration capacity targets.

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
| `/screenshotServe?key=...` | Redirect through App Engine Images service | Stable screenshot asset route |
| `/reportapp` | Public report form and Mail-service submission | Rebuild or explicitly retire after review |
| `/card/{revision}/version` | RetroStore Card firmware version | Firmware compatibility route |
| `/card/{revision}/firmware` | RetroStore Card firmware bytes | Firmware compatibility route |
| `/trs-io/{revision}/version` | TRS-IO firmware version | Firmware compatibility route |
| `/trs-io/{revision}/firmware` | TRS-IO firmware bytes | Firmware compatibility route |
| `/card`, `/trs-io` | Authenticated firmware admin | New Flask admin |
| `/rpc?m=<method>` | Polymer admin RPC surface | Replace with server-rendered admin forms |
| `/post/uploadDiskImage` | Admin media upload | New Flask admin upload |
| `/screenshotUpload*`, `/screenshotUrlForUpload*` | Blobstore screenshot upload | New Flask admin upload |
| `/import*` | Authenticated RPK import | New Flask admin workflow |
| `/updateData` | Search-index refresh | Removed after search migration |
| `/ping` | One-minute App Engine warmup cron | Remove only at App Engine retirement |

The legacy `/rpc` registry contains:

- `userlist`, `getSiteContext`, `addEditUser`, and `deleteUser`.
- `addEditApp`, `getAppFormData`, `applist`, `pubapplist`, and `deleteApp`.
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
- Eight additional Blobstore objects are unreferenced. They must be preserved
  and investigated during migration rather than deleted automatically.

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

All current buckets use the `US` multi-region, Standard storage, and a seven-day
soft-delete policy:

| Bucket | Objects | Stored bytes | Purpose and notable policy |
| --- | ---: | ---: | --- |
| `trs-80.appspot.com` | 0 | 0 | Firebase/App Engine default bucket; no lifecycle rule |
| `staging.trs-80.appspot.com` | 0 | 0 | App Engine staging; delete objects after 15 days |
| `us.artifacts.trs-80.appspot.com` | 92 | About 1.35 GiB | Legacy Container Registry artifacts |

Uniform bucket-level access and object versioning are not enabled. The buckets
retain legacy project-owner/editor/viewer ACLs. None is an appropriate
least-privilege production asset store without policy changes; creating a new
private bucket is safer than repurposing the empty default bucket during the
parallel run.

The Artifact Registry API is enabled but has no repositories. The Cloud Run
Admin API is disabled and was deliberately left disabled during inventory, so
there are no existing Cloud Run services to preserve. Cloud Build is enabled.

The project has three user-managed/default service accounts: the App Engine
default account, the Compute default account, and the Firebase Admin SDK service
account. The App Engine and Compute default accounts currently hold the broad
Editor role. No migration-specific or Cloud Run runtime identity exists yet.

## Remaining data-migration work

Infrastructure discovery and Datastore, Blobstore, and Search reconciliation are
complete enough to choose the target topology. Remaining data work is:

- Investigate and classify the eight unreferenced Blobstore objects.
- Decide whether the ten legacy `RetroStoreUser` records become invited
  Firebase identities, disabled historical records, or both. Firebase Auth has
  no existing identities or configuration to merge.

Recommended target locations based on the observed topology are `nam5` for the
two named Firestore databases, `US` for the private asset bucket, and
`us-central1` for Cloud Run. This keeps new persistence aligned with the current
Datastore and bucket geography while placing compute in the corresponding
central US region. These locations should be explicitly approved before any
resource is created.

# RetroStore current-system inventory

Status: Partial, read-only inventory in progress

Last verified: 2026-08-05

This document records observed production and source behavior. Unknown values
remain explicit; no production resources were created or modified while
collecting it.

## Local cloud context

- gcloud project: `trs-80`
- gcloud account selected: `saschah@gmail.com`
- Firebase default project in this repository: `trs-80`
- Firebase project number: `760396810462`
- Firebase project state: `ACTIVE`

The selected gcloud user's refresh token currently fails with `invalid_grant`.
Commands that use gcloud APIs require an interactive `gcloud auth login` before
the remaining inventory can be completed. The Firebase CLI's existing login is
working and was used for the read-only Firebase observations below.

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

## App Engine runtime and dispatch

The deployed application source is a Java 11 WAR using the App Engine bundled
services. `MainServlet` handles both GET and POST through one priority-ordered
request chain. `ObjectifyFilter` wraps all paths.

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

Mutation-safe probes against `retrostore.org` on 2026-08-05 establish:

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

The reviewed initial golden baseline has twelve scenarios: one mutation-safe
protobuf scenario per method plus the three supported legacy JSON forms. It is
stored in `backend/tests/contract/golden/live-safe-baseline.json`.

Important legacy edge case: an empty `uploadState` message has no memory
regions, passes `allMatch`, and allocates a token. Contract probes must never use
an empty upload. The checked-in safe scenario includes a negative-start memory
region and is rejected before state storage.

## Datastore, Blobstore, and bundled-service data

Objectify registers exactly seven entity kinds:

| Kind | ID | Binary or relationship notes |
| --- | --- | --- |
| `AppStoreItem` | UUID string | Nested listing; four disk IDs; cassette, command, and BASIC IDs; ordered Blobstore screenshot keys |
| `Author` | Numeric | Indexed name |
| `MediaImage` | Numeric | App ID, filename, description, upload time, and inline bytes |
| `RetroCardFirmware` | `<revision>-<version>` | Inline firmware bytes |
| `TrsIoFirmware` | `<revision>-<version>` | Inline firmware bytes |
| `RetroStoreUser` | Email | Names and account type |
| `SystemState` | Token `100`–`999` | Registers, memory-region byte arrays, indexed creation timestamp |

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

## Remaining read-only inventory

Complete these after `gcloud auth login` refreshes `saschah@gmail.com`:

- App Engine application location, services, versions, traffic splits, and
  custom domains.
- Datastore kind counts and representative encoded entities.
- Blobstore object count, total bytes, and orphaned/referenced keys.
- Cloud Storage bucket names, locations, retention, versioning, IAM, and object
  counts.
- Cloud Run services and regions.
- DNS zones and current `retrostore.org` records.
- Existing load balancers, forwarding rules, IP addresses, URL maps,
  certificates, and network endpoint groups.
- Search-index document count and rebuild behavior.
- Current Firebase Authentication providers and whether the legacy users have
  corresponding Firebase identities.

No named database, bucket, service account, Cloud Run service, DNS record, or
load-balancer resource should be created until this inventory is complete and
the target location is approved.

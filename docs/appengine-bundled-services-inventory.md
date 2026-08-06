# App Engine bundled-services inventory operation

Status: Production-validated; temporary versions deleted

Last updated: 2026-08-06

## Purpose and boundary

Cloud Datastore exposes Blobstore metadata but cannot read the legacy object
bytes, and gcloud cannot enumerate the App Engine Search documents. The legacy
application therefore contains a narrowly scoped read-only operation that can
run beside those bundled services before migration.

The operation is not part of the public RetroStore API. It uses the exact path:

```text
GET /internal/migration/bundled-services-inventory
```

It requires the existing RetroStore `ADMIN` account type, emits
`application/json`, sets `Cache-Control: no-store` and `Pragma: no-cache`, and
does not add a CORS header. A non-admin receives HTTP 403, another HTTP method
receives HTTP 400, and an internal failure returns HTTP 500 without exception
details in the response.

## Read-only behavior

The implementation only calls bundled-service read operations:

- `BlobInfoFactory.queryBlobInfos()` enumerates Blobstore metadata.
- `BlobstoreService.fetchData()` reads bounded byte ranges.
- `Index.getRange()` enumerates Search documents in pages.
- `Index.getStorageUsage()` and `Index.getStorageLimit()` are attempted for
  optional index metrics. App Engine Java 25 reports them as unavailable, which
  is recorded without failing document reconciliation.
- `AppManagement.getAllApps()` reads the expected catalog documents.

There are no save, put, delete, upload, index-refresh, routing, or deployment
calls in the operation.

Blob contents are fetched in chunks no larger than
`BlobstoreService.MAX_BLOB_FETCH_SIZE`. Each chunk must have the exact requested
length or the complete operation fails. The operation computes SHA-256 and MD5
while streaming, accepts both hexadecimal and Base64 Blobstore metadata MD5
forms, and reports metadata mismatches.

Search documents are compared with the exact two fields constructed by the
legacy indexer: `name` and `description`, both as Search `TEXT` fields. The
comparison detects missing, stale, duplicate-ID, missing-ID, and content-drift
documents without returning any document ID or indexed value.

## Sanitized report contract

The JSON report has `schema_version` 1 and contains:

- A UTC generation time and explicit safety flags.
- Blob object count, total and largest size, bytes hashed, fetch count, duplicate
  key count, metadata-MD5 coverage/matches/mismatches, and one aggregate
  content SHA-256.
- Live and expected Search document counts, drift counts, an explicit storage
  information availability flag, optional storage usage/limit, field-name/type
  occurrence counts, and live/expected aggregate SHA-256 values.

The aggregate Blob digest is built from sorted blob keys, sizes, and the
per-object content SHA-256 values. The keys are inputs to the digest so object
identity affects reconciliation, but neither keys nor per-object digests are
serialized. Search aggregate digests similarly incorporate IDs, fields, types,
locales, and values without serializing those inputs.

The report explicitly states that it contains no Blobstore keys, Search
document IDs, indexed values, or binary data. Tests serialize reports populated
with sentinel secrets and assert that none appear in the JSON.

This aggregate report proves repeatability and detects drift. It intentionally
does not provide the key mapping needed to copy or individually classify the
eight currently unreferenced blobs; that belongs in a separately protected
migration artifact, not an HTTP response.

## Validation and controlled production use

Run the complete Java build locally:

```shell
./gradlew --no-daemon :appengine:build
```

The focused suite currently contains twelve tests for bounded reads, incomplete
reads, both MD5 encodings, deterministic hashing, Search reconciliation,
unsupported Java 25 storage metrics, serialized-data suppression, route
isolation, role/method enforcement, login-handler bypass, failure redaction,
and no-store response headers.

Three versions were deployed on 2026-08-06 using App Engine Java 25 in EE 8
compatibility mode, always with promotion disabled:

- `migration-inventory-20260806-111431`, the initial smoke-test candidate.
- `migration-inventory-20260806-112020`, which corrected login routing. Its
  first authenticated scan exposed that Java 25 throws
  `UnsupportedOperationException` for optional Search storage metrics after
  document enumeration.
- `migration-inventory-20260806-145211`, which records those metrics as
  unavailable while preserving complete Search reconciliation.

Two authenticated reports from the final candidate were captured at
`2026-08-06T15:01:51.775660456Z` and
`2026-08-06T15:04:41.064404258Z`. After excluding `generated_at`, both reports
have normalized SHA-256
`7ba290376c6641c511c7cd58b4b1a7c745d7ba2780d425903de69da84de4fb71`.
They establish:

- 98 Blobstore objects totaling 6,094,655 bytes, with a largest object of
  994,809 bytes.
- 6,094,655 bytes read and hashed across 98 bounded fetches.
- All 98 metadata MD5 values match the content; no duplicate keys or mismatches.
- Blob content aggregate SHA-256
  `dbeb8d33efcb59ddb28e341f483429e7d81b7452a82d1cce50d6f3dee6946aeb`.
- 32 live Search documents and 32 expected app documents, with no missing,
  stale, duplicate-ID, missing-ID, or content-mismatched documents.
- Matching live and expected Search aggregate SHA-256
  `e89144f61f87285b4b89fd2f718c2891c2aebfc25b213e3ad37f3c7fb4cf46c1`.
- Exactly 32 `TEXT` fields each for `name` and `description`.

The Blob counts, sizes, metadata-MD5 coverage, and Search count also match the
independent Datastore inventory. The two raw sanitized reports are retained in
the operator's gitignored `.migration-artifacts/` directory.

App Engine automatic-scaling versions cannot be stopped, so all three temporary
versions were deleted after validation. Production traffic stayed 100% on
`20230819t145020` throughout.

Do not change `retrostore.org`, the public `/api/*` routes, or production traffic
to run this operation.

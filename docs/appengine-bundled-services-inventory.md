# App Engine bundled-services inventory operation

Status: Implemented and locally tested; not deployed or run against production

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
- `Index.getStorageUsage()` and `Index.getStorageLimit()` read index metrics.
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
- Live and expected Search document counts, drift counts, storage usage/limit,
  field-name/type occurrence counts, and live/expected aggregate SHA-256 values.

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

The focused suite currently contains eleven tests for bounded reads, incomplete
reads, both MD5 encodings, deterministic hashing, Search reconciliation,
serialized-data suppression, route isolation, role/method enforcement,
login-handler bypass, failure redaction, and no-store response headers.

Corrected version `migration-inventory-20260806-112020` was deployed on
2026-08-06 using App Engine Java 25 in EE 8 compatibility mode with promotion
disabled. It is `SERVING` at 0% traffic, and an unauthenticated request to the
operation returned HTTP 403. The privileged inventory scan has not been run.
Superseded smoke-test version `migration-inventory-20260806-111431` also remains
at 0% traffic pending reviewed cleanup.

To collect the live report:

1. Authenticate as an existing RetroStore admin on the corrected version
   hostname.
2. Capture the report to a restricted migration-artifact location.
3. Repeat it and require identical aggregate digests and counts after excluding
   `generated_at`.
4. Compare its Blob counts/bytes with the Datastore inventory and its expected
   Search count with the catalog inventory.
5. Stop both temporary versions after the reviewed report is retained.

Do not change `retrostore.org`, the public `/api/*` routes, or production traffic
to run this operation.

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
compiles the checksum-pinned RetroStore client from the TRS-80 Kotlin
Multiplatform application through its five production calls, and compiles the
embedded C client through all three legacy JSON calls and nanopb decoding. The
clients talk over real loopback HTTP to the representative Flask candidate;
their synthetic state writes remain in memory.

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python \
  -m retrostore.contract.consumer_clients \
  --trs80-checkout /path/to/TRS-80
```

The reviewed TRS-80 revision, source checksums, dependency pins, and exact
coverage split are documented in `consumer-tests/README.md`. CI checks out only
the reviewed client source paths and runs this command independently of the
legacy Java build.

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
digests, counts, byte totals, and the aggregate digest.

The format and its current scope are in `retrostore/mirror/FORMAT.md`. No export
route is registered yet, and this implementation does not read or mutate
Firebase. A controlled non-promoted export operation and the production
Firestore/Cloud Storage adapter are the next pieces.

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

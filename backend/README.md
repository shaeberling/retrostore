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

Run either service locally from this directory:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run flask --app services.api_compat.app run --port 8080
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run flask --app services.admin.app run --port 8081
```

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

The baseline corpus covers every public method plus all three legacy JSON forms.
Its `uploadState` request is deliberately invalid and cannot allocate a token.

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python -m retrostore.contract.capture \
  --base-url https://retrostore.org \
  --output /tmp/retrostore-baseline.json

UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python -m retrostore.contract.compare_hosts \
  --reference-url https://retrostore.org \
  --candidate-url https://next.retrostore.org \
  --output /tmp/retrostore-comparison.json
```

The comparator exits nonzero on any transport or semantic difference. The
reviewed initial App Engine baseline is versioned under
`tests/contract/golden/`.

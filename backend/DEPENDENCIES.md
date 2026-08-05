# Backend runtime and dependency audit

Last audited: 2026-08-05

## Runtime decision

The backend uses standard CPython `3.14.6`.

- Python 3.14.6 is the current 3.14 maintenance release.
- Cloud Run accepts any language and base image that satisfies its container
  contract; the image must include `linux/amd64` and listen on the injected
  `PORT`.
- `python:3.14.6-slim-bookworm` is present in the Docker Official Images source
  of truth and its registry manifest includes `linux/amd64`.
- Both service Dockerfiles use the exact Python patch release rather than a
  moving `3.14` tag.
- The project, CI, and local environment all use the normal GIL-enabled build;
  the free-threaded build is not needed for these Flask services.

Primary references:

- [Python 3.14.6 release](https://www.python.org/downloads/release/python-3146/)
- [Cloud Run container contract](https://docs.cloud.google.com/run/docs/container-contract)
- [Docker Official Python image source](https://github.com/docker-library/official-images/blob/master/library/python)

## Direct dependency audit

The table compares the initial lock with current stable PyPI metadata. Release
candidates and yanked releases are excluded.

| Dependency | Initial | Audited lock | Result |
| --- | ---: | ---: | --- |
| Python | 3.13.11 | 3.14.6 | Upgraded |
| `firebase-admin` | 7.5.0 | 7.5.0 | Current |
| `Flask` | 3.1.3 | 3.1.3 | Current |
| `google-cloud-firestore` | 2.28.0 | 2.28.0 | Current |
| `google-cloud-storage` | 3.13.0 | 3.13.0 | Current |
| `gunicorn` | 23.0.0 | 26.0.0 | Upgraded |
| `protobuf` | 6.33.6 | 7.35.1 | Upgraded |
| `grpcio-tools` | 1.81.1 | 1.83.0 | Upgraded |
| `httpx` | 0.28.1 | 0.28.1 | Current |
| `pytest` | 8.4.2 | 9.1.1 | Upgraded |
| `pytest-cov` | 7.1.0 | 7.1.0 | Current |
| `ruff` | 0.16.1 | 0.16.1 | Current |
| `uv` build tool | 0.11.6 | 0.12.1 | Upgraded |

The direct requirements use the current stable version as their lower bound and
the next major as an upper bound. `uv.lock` pins the complete graph exactly. A
new major therefore requires an explicit audited lock update rather than being
introduced during an ordinary build.

## Python 3.14 compatibility evidence

- `grpcio` and `grpcio-tools` 1.83.0 publish CPython 3.14 wheels for Linux
  `x86_64` and macOS ARM64, so neither local development nor the Cloud Run image
  needs to compile gRPC from source.
- Protobuf 7.35.1 supports Python 3.10 and newer and publishes an ABI3 wheel.
- Firestore, Storage, pytest, pytest-cov, Ruff, and uv explicitly classify
  Python 3.14 support in current PyPI metadata.
- Firebase Admin, Flask, Gunicorn, and HTTPX publish platform-independent Python
  wheels whose `Requires-Python` ranges include 3.14. They install and execute in
  the checked Python 3.14 environment.
- The generated `ApiProtos_pb2.py` now records Protobuf Python version 7.35.1.

## Complete graph audit

The locked environment contains 52 installed third-party packages. After an
upgrade resolution:

```text
uv tree --outdated            -> no outdated packages reported
uv pip list --outdated        -> []
uv pip check                  -> all installed packages are compatible
```

Validation under CPython 3.14.6:

- All 20 unit and contract tests pass with pytest 9.1.1.
- Ruff passes with `target-version = "py314"`.
- Both Gunicorn 26 application factories pass `--check-config`.
- The twelve mutation-safe live App Engine observations have zero differences
  from the reviewed golden baseline when captured with Python 3.14 and
  protobuf 7.
- The lockfile passes `uv lock --check` with the pinned uv 0.12.1 build tool.

## Repeat the audit

```shell
cd backend
uv lock --upgrade
uv sync --frozen
uv tree --outdated
uv pip list --outdated
uv pip check
uv run pytest
uv run ruff check .
```

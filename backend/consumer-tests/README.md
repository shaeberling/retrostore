# Public client compatibility tests

This standalone Gradle build runs deployed client implementations over real
HTTP against the representative Flask compatibility candidate. It is separate
from the legacy App Engine build so Kotlin and Wire tooling cannot affect the
production Java application.

The two suites cover different portions of the frozen API:

| Consumer | Source under test | Coverage |
| --- | --- | --- |
| JVM SDK | Published `org.retrostore:retrostore-client:0.2.13` artifact | All nine public methods, including both raw byte-range responses |
| TRS-80 KMP | Shared client, protobuf, application wiring, and Android/iOS/web transports from TRS-80 revision `aecbddcc7f5515fb844bb7a1fc350d8ffaaf5ce5` | The five methods exposed to the Android, iOS, and web application |
| TRS-80 embedded C | `backend.cpp`, its checked-in nanopb bindings, and cJSON from the same reviewed revision | All three legacy JSON request forms and nanopb catalog/detail/media decoding |

The Python runner requires that exact Git revision and verifies SHA-256 for the
reviewed KMP client, protobuf, shared application wiring, all three platform
HTTP transports, and every embedded C source compiled by the harness. The C test
replaces only the hardcoded socket connection with a loopback transport; its
request generation, cJSON, nanopb bindings, and response parsing remain upstream
code. It finds the reviewed media fixture through the native client's own
paginated catalog instead of assuming a fixture-only list position. This
intentionally avoids copying either client and silently letting that copy drift
from the application. The upstream application's unrelated
UI/resource build does not enter this test build.

The platform behavior is part of the gate even though the shared KMP client is
executed on the JVM in this fast integration suite:

| Application target | Production transport behavior protected by the reviewed sources |
| --- | --- |
| Android | HTTPS `HttpURLConnection` POST with an unlabelled protobuf body |
| iOS | HTTPS `NSURLSession` POST with an unlabelled protobuf body |
| Web | Browser `fetch` simple POST with no custom headers; requires wildcard CORS without preflight |
| Native C | Plain HTTP on port 80, form-labelled legacy JSON request, raw nanopb response decoding |

The TRS-80 repository's own Android/web build and macOS iOS build remain the
authoritative platform compilation gates. Before production cutover, all three
application targets must also complete an end-to-end run through the candidate
hostname and through the production load balancer; this loopback suite is not a
substitute for those platform runs.

Clone or check out the reviewed TRS-80 revision, then run from `backend/`:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python \
  -m retrostore.contract.consumer_clients \
  --trs80-checkout /path/to/TRS-80
```

The runner binds the representative Flask app to an ephemeral loopback port,
compiles/runs the embedded C client, runs both JVM suites, and shuts the server
down even when a consumer fails. Every state write is isolated in the in-memory
fixture; the command never writes to either deployed service.

Guarded external mode accepts only an exact `http://127.0.0.1:<port>` origin
provided by an authenticated Cloud Run proxy. It requires `--apply`, the exact
`--confirm-candidate-url`, and `--output`; the JVM and KMP clients then create
one short-lived synthetic state each. The output reports only pass/fail and
method coverage, never state tokens, response bodies, or credentials. The
JVM-only KMP transport adapter uses HTTP/1.1 in this mode because the gcloud
proxy does not accept a cleartext HTTP/2 upgrade. None of the checksum-pinned
production transport sources is modified.

The harness uses the KMP application's stable Kotlin 2.4.10, Wire 6.4.5, and
coroutines 1.11.0 versions. JUnit 6.1.2 was the current stable release when the
harness was added. Gradle verifies SHA-256 for the complete dependency graph
using `gradle/verification-metadata.xml`.

These are consumer integration tests, not the exhaustive data-mirror gate. The
representative fixture proves parsing, transport, media filtering, and state
behavior with bounded checked-in data. Full catalog and media comparison will
run separately against the synchronized candidate mirror so it can cover every
record without committing the public media archive to Git.

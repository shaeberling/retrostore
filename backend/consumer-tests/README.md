# Public client compatibility tests

This standalone Gradle build runs deployed client implementations over real
HTTP against the representative Flask compatibility candidate. It is separate
from the legacy App Engine build so Kotlin and Wire tooling cannot affect the
production Java application.

The two suites cover different portions of the frozen API:

| Consumer | Source under test | Coverage |
| --- | --- | --- |
| JVM SDK | Published `org.retrostore:retrostore-client:0.2.13` artifact | All nine public methods, including both raw byte-range responses |
| TRS-80 KMP | `RetrostoreClient.kt` and `ApiException.kt` from TRS-80 revision `79a8e5869aa1de2bfd896182abdf09fb557a261b` | The five methods used by the Android, iOS, and web application |
| TRS-80 embedded C | `backend.cpp`, its checked-in nanopb bindings, and cJSON from the same reviewed revision | All three legacy JSON request forms and nanopb catalog/detail/media decoding |

The Python runner verifies SHA-256 for the reviewed KMP and embedded C contract
sources before compiling them. The C test replaces only the hardcoded socket
connection with a loopback transport; its request generation, cJSON, nanopb
bindings, and response parsing remain upstream code. This intentionally avoids
copying either client and silently letting that copy drift from the application.
The upstream application's unrelated UI/resource build does not enter this test
build.

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

The harness uses the KMP application's stable Kotlin 2.4.10, Wire 6.4.5, and
coroutines 1.11.0 versions. JUnit 6.1.2 was the current stable release when the
harness was added. Gradle verifies SHA-256 for the complete dependency graph
using `gradle/verification-metadata.xml`.

These are consumer integration tests, not the exhaustive data-mirror gate. The
representative fixture proves parsing, transport, media filtering, and state
behavior with bounded checked-in data. Full catalog and media comparison will
run separately against the synchronized candidate mirror so it can cover every
record without committing the public media archive to Git.

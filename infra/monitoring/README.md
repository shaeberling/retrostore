# RetroStore monitoring design

The migration uses Cloud Run's native request count, request latency, instance,
startup, and job-execution metrics together with bounded structured application
events. The definitive thresholds are in
`../front-door/monitoring-thresholds.json`.

## Structured request event

Both Flask services emit one JSON object after every response with:

- `event=http_request`, service, Flask endpoint, severity;
- request method, status, request and response sizes, and latency in the
  recognized `httpRequest` object;
- the frozen API method name only for `/api/<method>`; and
- Cloud Trace correlation when the load balancer supplies a valid trace ID.

The event deliberately omits URL paths, query strings, client addresses, user
agents, cookies, authorization headers, Firebase identities, state tokens,
protobuf bodies, media bytes, and response bodies. Admin audit events remain in
Firestore and are not duplicated into request logs.

Useful Cloud Logging filters include:

```text
resource.type="cloud_run_revision"
jsonPayload.event="http_request"
jsonPayload.service="retrostore-api-compat"
```

```text
resource.type="cloud_run_job"
jsonPayload.event="scheduled_comparison"
jsonPayload.approval_gate.passes=false
```

## Required dashboard panels

- Request count by service, endpoint, API method, status class, and revision.
- 5xx count and ratio over five minutes, compared with the App Engine backend.
- p50, p95, and p99 latency by API method and revision.
- Cloud Run instance count, startup latency, container CPU, and memory.
- Latest readiness result and age for API and admin.
- Latest comparator execution, matching/total, artifact digest, and age.
- Catalog snapshot ID/readiness and last successful reconciliation age.
- State allocation failures, collisions, logical-expiry rejects, and object
  failures without recording tokens.
- Admin authentication rejects, CSRF rejects, authorization rejects, and audit
  commit failures without recording identities in metrics.

## Alerts

Page or immediately stop a canary for any unexplained comparison difference,
integrity error, possible data loss, state collision, writer-invariant failure,
or confirmed client compatibility failure. Availability and latency use the
checked-in rate, delta, volume, and observation windows. A stale comparator is a
failure: alert if no successful scheduled event is present for 90 minutes.

The first dashboard and alert resources should be created only after the private
job produces a successful retained artifact. Before a public hostname exists,
readiness checks remain authenticated and are not Google uptime checks.

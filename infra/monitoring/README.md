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

`dashboard.json` is the API-managed candidate dashboard. It contains native
Cloud Run request rate and p95 latency charts plus live comparator-evidence and
application-error log panels. Its fixed resource name makes later updates
explicit rather than creating duplicate dashboards.

`comparator-failure-policy.json` matches any non-passing approval gate.
`comparator-stale-policy.json` detects a 90-minute absence of the
`retrostore_comparison_pass` log-based counter. Both policies are deliberately
created disabled and without a notification channel. Confirming the responsible
recipient, attaching the channel, and enabling the policies are one explicit
operational handoff.

## Current private deployment

- Dashboard: `projects/760396810462/dashboards/retrostore-migration`
- Log metric: `retrostore_comparison_pass`
- Difference policy:
  `projects/trs-80/alertPolicies/10244504485702710710`
- Stale-evidence policy:
  `projects/trs-80/alertPolicies/2434770354521712482`

The dashboard and metric are active. Both alert policies are disabled and have
no notification channels, so they cannot notify an unintended recipient. Their
checked-in JSON remains the reviewable source for later updates. Enabling them
requires a confirmed operator and notification destination; the migration does
not infer those operational responsibilities.

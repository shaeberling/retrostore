# RetroStore monitoring design

The migration uses Cloud Run's native request count, request latency, instance,
startup, and job-execution metrics together with bounded structured application
events. The definitive thresholds are in
`../front-door/monitoring-thresholds.json`.

Validate the checked-in dashboard text, four-surface gate, 90-minute stale
threshold, disabled alert policies, absence of attached channels, and pending
recipient decision offline with:

```shell
python3 infra/monitoring/validate.py
```

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

The 2026-08-10 inventory reconfirmed exactly two disabled policies, neither with
an attached notification channel, one migration dashboard, and the comparison
pass metric. The dashboard gate text now reflects the schema-3 hourly surfaces
(API 158, downloads 94, website 32, redirects 6) and the separate 338-scenario
HTTP/HTTPS transport gate. The text-only dashboard update used the live etag;
no alert, channel, service, IAM, or traffic setting changed.

## Private capacity evidence

`retrostore.contract.load_test` replays only the exhaustive read corpus against
the authenticated private API candidate, compares every response with a fresh
production reference, and records aggregate request/latency evidence. Its
companion `retrostore.contract.cloud_run_metrics` reads ten native Cloud Run
metrics for the exact revision and load window, including allocation and
billable time. Both commands default to a no-network plan and require exact
target confirmations for execution.

The 2026-08-10 revision `retrostore-api-compat-candidate-observability2` run sent
2,000 measured requests at concurrency 8 after 16 warmups. It sustained 39.15
requests per second with 2,000 HTTP 200 responses, zero transport errors, zero
5xx responses, zero semantic differences, and passing provisional p95/p99
front-door gates for every API method. Cloud Monitoring independently reported
2,016 successful requests, one active instance, 1.97% mean CPU utilization,
42.90% mean memory utilization, and 3.94 ms mean in-container request latency
for the bounded window. The result establishes comfortable headroom for this
specific private read workload; it is not production-routing authority.

The completed ramp covered 15,000 measured requests and 1.301 GB of responses
with zero semantic differences, transport errors, or 5xx responses. Concurrency
8, 12, and 16 passed; concurrency 16 reached 62.05 requests per second but was
close to its provisional `listApps` p95 limit. Concurrency 20 reached 66.56
requests per second and preserved a non-passing media latency boundary. Native
telemetry still showed one instance, CPU p95 no higher than 26%, memory p95 no
higher than 45%, and in-container p95/p99 no higher than 12.1/17.72 ms. One
950.6 ms startup was observed. The concurrency-16 run consumed 54.4 billable
instance/CPU seconds and 27.2 GiB-seconds of memory allocation. No Cloud Run
configuration or traffic was changed.

The `downloads1` revision was also checked after private promotion. Its first
concurrency-8 run matched all 2,000 responses but preserved a provisional
`listAppsNano` latency non-pass from two client-observed stalls in a 13-request
sample; exact-revision native telemetry passed the evidence/resource gate. A
fresh 2,000-request confirmation passed every method gate at 38.08 requests per
second with zero semantic differences, transport errors, or 5xx responses.

The checksum-validating soak auditor currently sees ten retained comparison
reports. All ten API comparisons matched 158/158; the first seven predate
multi-surface evidence and are retained as API-only history. The schema-2 report
after the `website1` boundary also passed all 94 downloads and all 32 website
entries. The schema-3 report after the `redirects1` boundary additionally passed
all six exact public redirects, starting the current private evidence clock at
2026-08-10 03:55:01 UTC. Two schema-3 reports now extend that streak, including
the first automatic generation-4 execution. A gap over 90 minutes, a
failed/changed report, or a different serving revision makes the clock
non-current. Reaching fourteen days
will satisfy only this private evidence gate; it cannot substitute for the
separate hostname, ownership, front-door, consumer, or writer-handoff gates.

# RetroStore front-door preparation

This directory freezes the routing, deployed parallel-candidate baseline, and
operational gates. `route-groups.json` is the machine-readable source of truth,
`public-candidate-baseline.json` records the candidate-only resources that now
exist, and `monitoring-thresholds.json` contains conservative provisional
defaults. `private-soak-baseline.json` is retained as the historical filename;
it binds comparison evidence to one exact revision and deliberately denies
cutover authority. Run the
local, read-only check with:

```shell
python3 infra/front-door/validate.py
```

The validators in this directory are offline and never provision, update, or
delete a Google Cloud or DNS resource.

The approved final front door is the generated Worker in
`infra/cloudflare-worker/`. Its route arrays are derived from
`route-groups.json`; the existing Google URL-map fields and backend-bucket entry
remain an accurate record of the already-deployed temporary comparison stack.
They are not the intended production topology.

The current private evidence boundary is 2026-08-10 03:55 UTC, after revision
`retrostore-api-compat-candidate-redirects1` became ready at 100% private traffic
and comparator generation 4 was pinned to schema-3 four-surface evidence. Any
material service revision requires a reviewed baseline update and starts a new
three-report evidence streak. That historical private baseline explicitly
records the authority boundary that existed before candidate-only provisioning;
production routing and catalog activation remain unauthorized.

The first automatic generation-4 schedule fired at 04:17 UTC under the
comparator service account and retained a second eligible schema-3 artifact at
04:18:28 UTC. It passed the API (158/158), downloads (94/94), public catalog
(32/32), and redirects (6/6). The next hourly execution retained a third
eligible artifact at 05:19:27 UTC with the same zero-difference result. The
checksum auditor validated all eleven historical artifacts and reports three
current-boundary artifacts with no continuity gap. The separately deployed
public candidate is recorded in `public-candidate-baseline.json`.

## Verified current state

The candidate-only state was re-audited on 2026-08-10:

- `retrostore.org` and `www.retrostore.org` are direct App Engine domain
  mappings with App Engine-managed certificates.
- The separate `retrostore-next` global external Application Load Balancer is
  allocated at IPv4 `34.102.211.182` and IPv6 `2600:1901:0:81dc::`, with HTTP
  and HTTPS forwarding rules. It does not serve the production hostname.
- `retrostore-api-next` and `retrostore-admin-next` are distinct final services
  with explicitly approved public ingress and default URLs for Cloudflare
  origin access. Their pre-existing `allUsers` invoker bindings are unchanged;
  the admin retains Firebase session authorization. The earlier private
  comparison services remain unchanged.
- `trs-80-retrostore-public` contains the 78 checksum-verified static objects;
  its backend bucket has CDN disabled and adds the legacy CORS response header.
- The Google-managed Compute certificate for `next.retrostore.org` and
  `admin-next.retrostore.org` is `PROVISIONING` until their A/AAAA records exist.
- The domain now delegates to Cloudflare nameservers `curt` and `rita`. No
  candidate or production DNS record was changed by this work; record
  publication must be coordinated in that authoritative zone.
- The static-only `retrostore-public` Firebase Hosting origin is released. The
  generated Worker passed 11 local routing/proxy tests, bundled successfully,
  and was uploaded as `retrostore-front-door-preview` without custom-domain
  routes. Its active `workers.dev` preview passed all 79 static and 12 App
  Engine fallback comparisons with zero differences.
- `next.retrostore.org` and `admin-next.retrostore.org` are active Cloudflare
  Worker Custom Domains on candidate version
  `86cff09e-7510-498f-98f3-c9f61c4adf7d`. The complete 350-case candidate
  surface and pinned clients pass over HTTPS and plain HTTP; the admin login
  page passes and its Firebase redirect origin is deployed.
- No production DNS record, domain mapping, route, or invoker policy changed.

Pre-DNS HTTP probes use the reserved IPv4 address plus an explicit approved
Host header, so they are independent of public DNS. That front door passes
350/350 scenarios: API 158, downloads 94, public listing 1 (32 entries),
redirects 6, static routes 79, and App Engine fallbacks 12. HTTPS and real-client
candidate testing remain blocked until DNS and the certificate are ready. A
separate guarded 34-byte synthetic lifecycle also passed all three state RPCs.
The revision- and checksum-pinned JVM SDK, TRS-80 KMP client, and embedded C
client also pass through a guarded loopback bridge to the actual load balancer;
only direct public DNS/TLS transport remains to repeat after activation.

Production remains untouched until the complete replacement has passed
side-by-side testing. The Worker is exercised on its own candidate hostname
first; the production change is then one reversible route binding to that
already-tested script. The Cloudflare DNS origin remains App Engine during the
rollback window, so disabling the route restores the legacy front door.

## Approved candidate hostnames

| Purpose | Hostname | Initial target |
| --- | --- | --- |
| Complete parallel replacement | `next.retrostore.org` | New static site and Cloud Run routes, with explicitly retained App Engine fallback routes |
| Administration candidate | `admin-next.retrostore.org` | Cloud Run administration service |
| Production | `retrostore.org` | App Engine until the single cutover gate passes |

The two candidate names and both owners are approved. Sascha Ha is the confirmed
go/no-go owner and rollback operator. DNS records are deliberately still absent
while the domain move is coordinated.

## Route safety model

The frozen nine-method `/api` contract is split into three routing units:

- Catalog reads: `getApp`, `listApps`, and `listAppsNano`.
- Media reads: `fetchMediaImages`, `fetchMediaImageRefs`, and
  `fetchMediaImageRegion`.
- State: `uploadState`, `downloadState`, and
  `downloadStateMemoryRegion` as one atomic group.

All migrating groups use one atomic production route change; percentage splits
are disabled. State cannot be split because token allocation and retrieval must
share one authority. The new and legacy catalog admins also cannot run as
concurrent writers.

`/card`, `/card/*`, `/trs-io`, and `/trs-io/*` form a permanent App Engine
island. This includes both their public hardware update bytes and their
authenticated administration. They are validation exclusions, not a later
Cloud Run phase.

All unclassified paths default to App Engine. This fail-closed default prevents
a newly discovered legacy endpoint from accidentally reaching a partial Cloud
Run implementation. `/reportapp` and the Polymer RPC/upload/import routes remain
on App Engine. `/screenshotServe` is part of that login-protected Polymer admin
surface, not a public asset route; it retires only with the old admin. The
separately classified read-only `/downloadapp` route now has a tested private
Cloud Run implementation but no production routing authority. The six exact
`/community[/]`, `/rsc[/]`, and `/app[/]` redirects are also implemented by the
candidate with the legacy empty-body 302 behavior; longer paths remain
unclassified and fail closed to App Engine.

The static route group enumerates `/` plus every one of the 78 verified object
paths, including the legacy `/public/` aliases. It intentionally uses no broad
asset prefix: missing paths have inconsistent legacy fall-through behavior and
must continue to reach App Engine. The Worker targets the static-only
`retrostore-public.web.app` origin; the temporary Google URL map still targets
the deployed backend bucket.
It shares one `public_website` handoff group with `/public/apps.json` and the six
redirects, so those three backends change or roll back in one Worker deployment.
Because the dynamic `/public/apps.json` path is not a static object, there is no
static/dynamic route overlap to resolve. Validation rejects every undeclared
exact/prefix overlap, all duplicate exact routes, and all overlapping prefixes.

A separate 12-scenario fallback corpus covers an unknown root path, one missing
object in each legacy asset family, `/public/`, a redirect near-miss, a download
near-miss, and an unknown API method. Tests prove none is claimed by a migrating
route group. The live HTTP-versus-HTTPS baseline passed 12/12 while retaining no
response body: the observed behaviors include legacy login fall-through, empty
and body-bearing 404s, and bounded 400s. The final pre-cutover gate must compare
this corpus through the candidate front door and App Engine reference, in
addition to the 338 known public reads.

Run the read-only fallback comparison with:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run --directory backend python \
  -m retrostore.contract.front_door_fallbacks \
  --reference-url https://retrostore.org \
  --candidate-url https://CANDIDATE_HOST \
  --output ../.migration-artifacts/front-door-fallbacks.json
```

The local static deployment planner now verifies the complete bundle and emits
only create-if-absent upload descriptions. It cannot call Cloud Storage, refuses
the private assets/state and Firebase/App Engine buckets, never emits deletes,
and never marks a plan deployable. Every plan requires the bucket website
`mainPageSuffix` to be `index.html`; this preserves `/` without an unsupported
full-path URL-map rewrite. It deliberately leaves `notFoundPage` unset until
missing-path behavior is compared, so the public `/404.html` object does not
silently become a different response for every missing object.

The approved small-project policy uses the single dedicated
`trs-80-retrostore-public` bucket in `us-central1`. Its static objects are
publicly readable, public access prevention is disabled only on that bucket,
Cloud CDN is disabled initially, and objects begin with `Cache-Control:
no-store`. CDN remains a future opt-in optimization if measured traffic or
latency ever justifies it.
Application assets and state stay in their existing private buckets. The
emitted front-door section carries all 79 exact paths, zero prefixes, App Engine
as the unknown-path default, and the JSON/redirect companion routes that must
move atomically. The planner still cannot create the bucket or IAM binding.

Primary reference: [Cloud Storage static website configuration](https://cloud.google.com/storage/docs/hosting-static-website).

## Why active comparison is required

The Worker deliberately routes one request to one origin. It does not shadow or
replay traffic, because state uploads and legacy handlers can have side effects.
Therefore the complete corpus remains an explicit comparator and no real state
upload is ever replayed.

Serverless NEG backend services do not accept load-balancer health checks.
Readiness must instead be verified with direct authenticated candidate probes,
Cloud Run revision health, synthetic uptime checks after a public candidate is
approved, and the scheduled comparator.

## Remaining activation sequence

1. Complete the one remaining interactive candidate gate: Google sign-in and
   authorized admin navigation through `admin-next.retrostore.org`.
2. Capture a fresh synchronized-catalog/state readiness packet and confirm that
   App Engine remains the sole catalog writer until the handoff.
3. Confirm the alert recipient and review the final go/no-go packet.
4. Bind the already-tested Worker to `retrostore.org` once. Disabling that route
   returns traffic to the App Engine DNS origin immediately; there is no fixed
   waiting period or percentage rollout.

## Monitoring and rollback defaults

The checked-in thresholds require three consecutive fresh full comparisons
with zero differences; the existing streak already satisfies that gate.
Integrity tolerances are all zero. Percentage canaries and fixed observation
windows are disabled. The one production switch requires the complete corpus,
HTTP/HTTPS and native port-80 parity, and every pinned real-client smoke. State
and admin authority still move atomically so writes never split between stacks.

The same pre-cutover parity gate covers `/downloadapp`. Its normalized
mirror handler passed all 94 current ZIP, typed-media, and error scenarios
against App Engine before any route was created. ZIP comparison is semantic
because the legacy endpoint embeds request-time ZIP metadata.

Availability rollback triggers at 1% unexpected 5xx responses over five minutes
with at least 100 requests, a 0.25 percentage-point regression from App Engine,
or five unexpected 5xx responses at lower traffic. Latency must stay within both
the recorded relative and absolute guardrails. Any compatibility, integrity,
security, data-loss, state-allocation, or single-writer failure stops the change
immediately. The route recovery objective is five minutes.

These are conservative defaults that keep the work executable. A fresh explicit
go/no-go decision is still required before production traffic moves.

## Plain HTTP compatibility

Plain HTTP on port 80 is a migration requirement, not a cutover-time option.
The pinned TRS-80 native client connects to `retrostore.org:80` with a raw
socket, and this repository's ESP32 client also has `DEFAULT_PORT = 80` with an
open HTTPS TODO. Cloudflare therefore runs the same Worker on HTTP and HTTPS;
zone-level `Always Use HTTPS` and redirect rules must remain disabled. A future HTTP deprecation may
only happen as a separate client migration after a complete deployed-consumer
inventory proves no remaining dependency. A safe production probe on 2026-08-10
also confirmed that `POST http://retrostore.org/api/listApps` returns HTTP 200,
an empty redirect target, and the protobuf media type; redirecting would change
today's observable contract.

The complete public-read transport gate also matched HTTPS and plain HTTP across
338/338 scenarios: 158 API cases, 94 legacy downloads, six redirects, 79 static
routes, and the public listing. The machine-readable cutover policy requires
that full parity run plus the pinned native port-80 smoke before the single
production switch. This transport gate is separate from the schema-3 private
Cloud Run evidence streak.

## Google Cloud references

- [Global external Application Load Balancer with serverless backends](https://cloud.google.com/load-balancing/docs/https/setup-global-ext-https-serverless)
- [Global traffic management and serverless mirroring limitation](https://cloud.google.com/load-balancing/docs/https/traffic-management-global)
- [Certificate Manager DNS authorization](https://cloud.google.com/certificate-manager/docs/domain-authorization)
- [Cloud Run load-balancer security](https://cloud.google.com/run/docs/securing/security)

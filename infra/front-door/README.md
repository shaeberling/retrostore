# RetroStore front-door preparation

This directory freezes the proposed routing and operational gates without
creating cloud resources. `route-groups.json` is the machine-readable source of
truth and `monitoring-thresholds.json` contains conservative provisional
defaults. `private-soak-baseline.json` binds the current private comparison
clock to one exact revision and deliberately denies cutover authority. Run the
local, read-only check with:

```shell
python3 infra/front-door/validate.py
```

No script in this directory provisions, updates, or deletes a Google Cloud or
DNS resource.

The current private soak boundary is 2026-08-10 03:16 UTC, rounded up after
revision `retrostore-api-compat-candidate-website1` became ready at 100%
private traffic. Any
material service revision requires a reviewed baseline update and starts a new
clock. The baseline explicitly records that production routing, catalog
activation, and load-balancer provisioning remain unauthorized.

## Verified current state

The read-only inventory was refreshed on 2026-08-10:

- `retrostore.org` and `www.retrostore.org` are direct App Engine domain
  mappings with App Engine-managed certificates.
- The project has no Compute URL maps, backend services, network endpoint
  groups, global forwarding rules, or load-balancer IP addresses.
- The Certificate Manager API is disabled and has no project resources.
- All three replacement Cloud Run services remain private and use `ingress=all`
  only so authenticated `run.app` proxy testing works.
- No production DNS record, domain mapping, route, or invoker policy changed.

The initial production URL map is deliberately trivial: every request goes to
the App Engine backend. The load-balancer front-door move and backend cutover
are separate changes with separate soak clocks.

## Proposed hostnames

| Purpose | Proposed hostname | Initial target |
| --- | --- | --- |
| Full front-door rehearsal | `lb-next.retrostore.org` | App Engine only |
| API and screenshot candidate | `next.retrostore.org` | Cloud Run only for `/api/*`, `/s/*`, and `/assets/screenshots/*`; App Engine default |
| Administration candidate | `admin-next.retrostore.org` | Cloud Run administration service |
| Production | `retrostore.org` | App Engine only until each route gate passes |

These names are proposals, not DNS records. They and the named go/no-go and
rollback owners remain explicit confirmation items. The suggested owner for
both roles is Sascha Ha; the machine-readable plan does not record that as a
confirmed assignment.

## Route safety model

The frozen nine-method `/api` contract is split into three routing units:

- Catalog reads: `getApp`, `listApps`, and `listAppsNano`.
- Media reads: `fetchMediaImages`, `fetchMediaImageRefs`, and
  `fetchMediaImageRegion`.
- State: `uploadState`, `downloadState`, and
  `downloadStateMemoryRegion` as one atomic group.

Only the two read-only groups may use weighted backend services. State cannot
be split because token allocation and retrieval must share one authority. The
new and legacy catalog admins also cannot run as concurrent writers.

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
Cloud Run implementation but no production routing authority.

## Why active comparison is required

Global external Application Load Balancers support host/path routing and
weighted backend services, but request mirroring is not supported for serverless
NEGs. Therefore the complete corpus remains an explicit scheduled comparator;
the load balancer is not used to shadow state-changing traffic. No real state
upload is ever replayed.

Serverless NEG backend services do not accept load-balancer health checks.
Readiness must instead be verified with direct authenticated candidate probes,
Cloud Run revision health, synthetic uptime checks after a public candidate is
approved, and the scheduled comparator.

## Provisioning sequence requiring explicit approval

The following steps intentionally have no executable apply script yet:

1. Confirm the three proposed hostnames and the decision and rollback owners.
2. Enable Compute, Certificate Manager, and required load-balancing APIs.
3. Reserve global IPv4 and IPv6 addresses.
4. Create App Engine and Cloud Run serverless NEGs and one backend service per
   independently routed backend.
5. Create the App Engine-only URL map and both port-80 and port-443 frontends.
   Plain HTTP must not redirect while reviewed embedded clients still use it.
6. Create Certificate Manager DNS authorizations and add only their CNAME
   records. This lets certificates become active before any A or AAAA change.
7. Attach an active certificate map, then test with `curl --resolve` and all
   real consumers before publishing candidate A and AAAA records.
8. Expose separately deployed final Cloud Run services through the load
   balancer. Their application-facing paths need unauthenticated invocation;
   use `internal-and-cloud-load-balancing` ingress and disable their default
   URLs so the load balancer is the only public path. Do not loosen the current
   private candidate services in place.
9. Soak `lb-next.retrostore.org` with the App Engine-only map, then update
   `retrostore.org` only after certificates, IPv4, IPv6, HTTP, HTTPS, and the
   complete client matrix pass.
10. Keep the production URL map App Engine-only for at least 48 hours. Later
    backend moves are independent, reversible URL-map changes.

The existing App Engine-managed certificates cannot be attached to the new load
balancer. DNS authorization is selected because it permits the replacement
certificate to be provisioned before the production apex points at the load
balancer.

## Monitoring and rollback defaults

The checked-in thresholds require hourly full comparisons and fourteen
continuous zero-diff days. Integrity tolerances are all zero. Read canaries use
1%, 5%, 25%, 50%, and 100% steps with at least 24 hours at each step. Each step
must pass a fresh complete corpus. State and admin handoffs are atomic.

The same weighted read-canary sequence now covers `/downloadapp`. Its normalized
mirror handler passed all 94 current ZIP, typed-media, and error scenarios
against App Engine before any route was created. ZIP comparison is semantic
because the legacy endpoint embeds request-time ZIP metadata.

Availability rollback triggers at 1% unexpected 5xx responses over five minutes
with at least 100 requests, a 0.25 percentage-point regression from App Engine,
or five unexpected 5xx responses at lower traffic. Latency must stay within both
the recorded relative and absolute guardrails. Any compatibility, integrity,
security, data-loss, state-allocation, or single-writer failure stops the change
immediately. The route recovery objective is five minutes.

These are conservative defaults that keep the work executable; owner
confirmation is still required before production traffic moves.

## Google Cloud references

- [Global external Application Load Balancer with serverless backends](https://cloud.google.com/load-balancing/docs/https/setup-global-ext-https-serverless)
- [Global traffic management and serverless mirroring limitation](https://cloud.google.com/load-balancing/docs/https/traffic-management-global)
- [Certificate Manager DNS authorization](https://cloud.google.com/certificate-manager/docs/domain-authorization)
- [Cloud Run load-balancer security](https://cloud.google.com/run/docs/securing/security)

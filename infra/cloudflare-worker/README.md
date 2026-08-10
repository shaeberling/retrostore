# Cloudflare compatibility front door

This Worker is a path router, not a cache or application backend. It preserves
plain HTTP for the frozen native-client contract while using HTTPS for all
cross-provider origin calls:

- the 79 exact public website routes go to `retrostore-public.web.app`;
- the 17 exact and two prefix replacement routes go to `retrostore-api-next`;
- `admin-next.retrostore.org` goes to `retrostore-admin-next`;
- every other candidate public path passes through to the explicit
  `https://retrostore.org` App Engine origin for the Card, TRS-IO, report,
  legacy administration, and unknown-path compatibility surface.

The route arrays are generated from `infra/front-door/route-groups.json` and
CI fails if they become stale. Responses are returned as fixed-length byte
arrays so the raw C and ESP32 clients retain `Content-Length` and never see a
Cloudflare-to-origin HTTPS redirect. Firebase MIME types are normalized to the
legacy contract. Redirects are never followed by the Worker.

Install and test:

```shell
npm install
npm test
```

The default deployment creates only a `workers.dev` preview:

```shell
WRANGLER_LOG_PATH=/tmp/retrostore-wrangler.log npm run deploy:preview
```

The current isolated upload completed on 2026-08-10 as version
`1b0be171-0284-45eb-a73e-98fcf7a188b7`, with no custom-domain route. Cloudflare
then activated the account subdomain at
`retrostore-cloudflare-worker.workers.dev`. The deployed preview passed all 79
static contract checks and all 12 App Engine fallback checks against production
with zero differences.

The operator explicitly approved and enabled default `run.app` URLs plus
`ingress=all` on only `retrostore-api-next` and `retrostore-admin-next`. The
Worker cannot reach load-balancer-only Cloud Run ingress. The two
non-production origins are now directly reachable: the API is intentionally
public, while the admin still enforces Firebase session authorization. This did
not alter production DNS.

The `candidate` environment also binds `next.retrostore.org` and
`admin-next.retrostore.org` as Cloudflare Worker Custom Domains. Cloudflare will
create their DNS records and certificates during the candidate deployment. Do
not deploy it until `Always Use HTTPS` is off, both Cloud Run default URLs are
enabled, and the complete preview corpus passes. Candidate App Engine fallback
uses `https://retrostore.org` explicitly because `next.retrostore.org` is not an
App Engine custom-domain mapping. No production Worker route is checked in;
adding `retrostore.org` as a route with same-host DNS-origin fallback is an
explicit cutover operation after the candidate passes.

The candidate was deployed on 2026-08-10 as version
`86cff09e-7510-498f-98f3-c9f61c4adf7d`. Cloudflare created both Custom Domains
and their certificates. The complete API, download, catalog, redirect, static,
fallback, synthetic-state, and pinned-client gates pass on
`next.retrostore.org` over HTTPS and plain HTTP. The retained Card and TRS-IO
version/binary probes are byte-identical and preserve `Content-Length`. Firebase
Auth now includes `admin-next.retrostore.org`; the login page and pre-session
redirect pass, while a final interactive Google sign-in remains a human gate.
The sanitized deployed-state record is `candidate-baseline.json`.

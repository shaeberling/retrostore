# Public static website candidate

The current public pages are static, but `apps.html` has one dynamic dependency:
the public legacy JSON call `/rpc?m=pubapplist`. The Flask compatibility service
reconstructs that response from the verified normalized mirror at the
unambiguous path `/public/apps.json`. Its 32 current entries match production
field-for-field.

Build a create-only candidate bundle without deploying anything:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run --directory backend python \
  -m retrostore.public_site \
  --output /tmp/retrostore-public-site \
  --report ../.migration-artifacts/public-site-build.json \
  --apply \
  --confirm-output /tmp/retrostore-public-site
```

The builder copies the existing public pages and vendored browser assets, adds
the legacy favicon and graphics directories, changes only the catalog fetch to
`/public/apps.json`, normalizes the two lightbox paths, removes two references
to a missing unused `contact_me.js`, validates local asset closure, and records
a deterministic aggregate digest. It refuses to replace an existing output or
report.

The route-closed build on 2026-08-10 contains 78 objects and 4,652,747 bytes,
has zero missing local asset references and zero unrouted objects, and produces
aggregate SHA-256
`991c3fabcc2b3fa359c34ad7b57a90510a54ce8de8cbbed1ff96b3b4a5aabf0b`.
It includes real `/public/` alias objects because the legacy static handler
exposes that tree; no load-balancer path rewrite is needed. The future route set
contains `/` and 78 exact object paths rather than directory prefixes. This
preserves App Engine's existing behavior for missing asset paths, which varies
between login fall-through and 404 depending on the legacy handler. The build
report has a size, checksum, and legacy-compatible content type for every object.

A bounded live comparison checked all 78 objects plus `/` against App Engine.
All 79 status, source-byte, content-type, CORS, and candidate-output gates
passed. Six HTML objects are intentionally transformed: root and `/public/`
copies of `apps.html`, `contact.html`, and `signup.html`. The other 72 objects
are byte-identical to their deployed legacy source.

The existing default Firebase Hosting site `trs-80` is the separately deployed
TRS-80 KMP web application. It must not be reused or overwritten by this
bundle. The checked-in front-door design instead uses a dedicated Cloud Storage
backend bucket. No bucket, load balancer, Firebase site, DNS record, certificate,
or public IAM binding is created here; those remain behind the explicit
hostname/ownership and front-door approval gate.

The legacy `/community[/]`, `/rsc[/]`, and `/app[/]` redirects cannot be served
by the static bundle itself. Their six exact paths have an empty-body 302
implementation in the private Flask compatibility candidate and are a separate
atomic route group. The scheduled comparator checks their status, destination,
content type, body length, and body digest without following them.

Static objects, the exact dynamic `/public/apps.json` route, and the six
redirects share the `public_website` atomic handoff group. The exact JSON route
is deliberately absent from the exact static-object set. A partial move would
strand either the catalog page or one of its legacy entry points.

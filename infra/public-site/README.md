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

The first complete build on 2026-08-10 contained 48 files and 2,909,581 bytes,
had zero missing local asset references, and produced aggregate SHA-256
`d892c9f2f067ed6a3b07e094f128cb22f26f822c7c3af4f15e5de20e0cd55b76`.

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

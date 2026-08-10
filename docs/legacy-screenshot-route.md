# Legacy screenshot route disposition

`/screenshotServe?key=...` is an authenticated Polymer-admin preview endpoint,
not part of the public RetroStore API contract.

The App Engine request order places `ScreenshotRequest` after `LoginRequest`.
`/screenshotServe` is not in the login whitelist. Read-only production probes
on 2026-08-10 confirmed that anonymous requests with a missing key, an invalid
key, and a known valid referenced Blobstore key all returned HTTP 200 with the
same 309-byte admin-login forwarding page. The valid key was read from a
protected local migration artifact and was not printed or retained in this
document.

The repository-wide consumer search found only the obsolete Polymer admin image
element. The pinned `/Users/sascha/source/TRS-80` KMP tree contains no
`screenshotServe` reference. Public catalog calls already return the direct
legacy App Engine Images serving URLs preserved as `legacy_serving_url`; new
screenshots use the checksum-verified RetroStore-owned `/s/<id>` route.

Consequently:

- `/screenshotServe`, `/screenshotUpload*`, and the screenshot management RPCs
  remain together on App Engine while the legacy admin is available;
- the new Flask admin uses its isolated screenshot workflow and `/s/<id>`
  previews instead;
- no public Cloud Run compatibility handler or Blobstore-key lookup table is
  needed; and
- the route can retire only at the reviewed atomic legacy-admin writer handoff.

This classification does not authorize a production route change or removal of
the legacy admin.

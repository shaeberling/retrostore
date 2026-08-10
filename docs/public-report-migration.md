# Public application-report migration

`/reportapp` is a small public website feature, not part of the frozen
nine-method protobuf API. It still needs an explicit disposition before the
legacy public website and catalog administration can leave App Engine.

## Current behavior

`ReportAppRequest` is evaluated before the login handler, so both its form and
submission are anonymous. The static app catalog links to it with
`/reportapp?appId=<legacy-id>`.

The GET form:

- requires an `appId` query parameter;
- rejects an unknown app;
- renders the legacy app name and first screenshot when the app exists; and
- collects reporter name, reporter email, and a free-form message.

The POST handler requires all four form values, verifies the app still exists,
then sends one email with the app ID/name and the three reporter-supplied
values. The App Engine implementation has two recipients and its sender wired
into Java source. It stores no queue, delivery state, or audit record. A mail
failure returns an HTML error with HTTP 200; a successful send returns an HTML
thank-you message with HTTP 200.

Safe production probes on 2026-08-10 established the externally visible
validation boundary without making a valid submission or sending mail:

| Request | Result |
| --- | --- |
| GET with no `appId` | 400, `'appId' missing.` |
| GET with an unknown `appId` | 400, `App not found` |
| POST with no `appId` | 400, `No appId given` |
| Fully populated POST with an unknown `appId` | 400, `Cannot find app with the given ID..` |
| GET with a current app ID | 200 HTML form |

No production mutation probe is appropriate: a valid POST has the external
side effect of emailing people.

## Data and security boundary

The route accepts personally identifiable information from an unauthenticated
browser. A replacement therefore needs, at minimum:

- strict field and total-request size limits;
- email syntax validation without treating the address as an identity;
- HTML escaping on every display and no reporter-supplied mail headers;
- CSRF protection where it is effective, plus rate limiting and automated-abuse
  protection for an anonymous endpoint;
- privacy-safe logs that never contain the name, address, message, or app ID;
- an explicit retention period and deletion workflow for any stored report;
- create-only writes so retries cannot overwrite an earlier report; and
- administrator-only review, status changes, and deletion with audit events.

Browser-direct Firestore or Storage writes are a poor fit. They would expose a
new anonymous client security-rules boundary, make abuse controls harder, and
couple the website to a storage schema. The server should continue to own the
HTTP contract and perform the write with a narrowly scoped identity.

## Options

### 1. Private admin queue (recommended)

Accept the legacy form in Flask, create an immutable report in an isolated
private store, and add a compact Reports page to the server-rendered admin.
Administrators can mark an item reviewed or delete it. Optional email
notifications can be added later without making email delivery the durable
record.

The least-privilege storage variant is a dedicated private reports bucket. The
public service receives only create permission and always uses
`if_generation_match=0`; the admin service receives read/update/delete access.
Object names are random IDs and contain no app or reporter value. A lifecycle
rule enforces the approved maximum retention even if an administrator never
reviews an item. Review state and audit events can remain in the durable
`retrostore` database and refer to the opaque object ID and content digest.

This does add one small bucket, but avoids granting the public API identity
write access to the durable catalog database. Firestore IAM is database-scoped,
not collection-scoped, so placing anonymous submissions directly in
`retrostore` would give the accepting service more authority than it needs. A
third Firestore database would also isolate the data but adds more operational
surface than this volume justifies.

### 2. Preserve email-only delivery

Replace App Engine Mail with a supported mail provider and preserve the current
success/error behavior. This is the smallest UI change but requires confirmed
recipients, sender/domain setup, secret management, provider monitoring, spam
controls, and an explicit answer for delivery failures. It still has no admin
history unless the provider is treated as the archive.

### 3. Retire reporting

Remove the report link from the new static catalog and return a deliberate
replacement page or terminal status at `/reportapp`. This has the smallest
security and maintenance footprint, but it is an intentional product behavior
change rather than an in-place compatible replacement.

## Decision and implementation gate

The recommended choice is the private admin queue. Implementation must wait for
an explicit choice among the three options and, for a queue, confirmation of
the retention period. Email notifications additionally require confirmed
recipients and sender policy. Until then `/reportapp` remains on App Engine and
the front-door configuration defaults it there.

This gate does not block the frozen client API, private compatibility comparison,
public static bundle preparation, or the replacement catalog administration.

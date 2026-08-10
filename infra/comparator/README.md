# Scheduled compatibility comparator

`retrostore.contract.scheduled_compare` runs the exhaustive catalog/media corpus
against `https://retrostore.org` and an authenticated private Cloud Run
candidate. It is strictly read-only: the discovered corpus excludes
`uploadState`, and the job has no Firestore or state-bucket permissions.

Each execution obtains a short-lived audience-bound Google identity token from
Application Default Credentials, compares all 158 current scenarios, and
conditionally creates a report below:

```text
gs://trs-80-retrostore-assets/operations/comparisons/YYYY/MM/DD/
```

Object names contain a timestamp and content digest, and creation uses a zero
generation precondition. Tokens, request bodies, media bytes, state values, and
admin identities are never logged or stored in the report. A compact structured
summary is emitted to Cloud Logging. A non-passing approval gate makes the job
exit unsuccessfully after retaining the evidence.

## Least-privilege deployment design

Use a dedicated `retrostore-comparator@trs-80.iam.gserviceaccount.com` identity
with only:

- service-scoped `roles/run.invoker` on
  `retrostore-api-compat-candidate`;
- object-create permission restricted to the durable report prefix; and
- service-scoped `roles/run.invoker` on the comparator job so Cloud Scheduler
  can start it.

It must not receive Firestore, state bucket, asset read, object delete, object
overwrite, project-wide Run invoker, or service-account token-creator roles.
The candidate service remains private.

The API container image is also a valid job image because the job overrides the
Gunicorn command:

```shell
gcloud run jobs deploy retrostore-hourly-comparator \
  --project trs-80 \
  --region us-central1 \
  --image API_IMAGE_DIGEST \
  --service-account retrostore-comparator@trs-80.iam.gserviceaccount.com \
  --command python \
  --args=-m,retrostore.contract.scheduled_compare \
  --set-env-vars RETROSTORE_PROJECT=trs-80,RETROSTORE_REFERENCE_URL=https://retrostore.org,RETROSTORE_CANDIDATE_URL=PRIVATE_CANDIDATE_URL,RETROSTORE_COMPARISON_BUCKET=trs-80-retrostore-assets \
  --tasks 1 \
  --max-retries 0 \
  --task-timeout 15m \
  --memory 512Mi \
  --cpu 1
```

The first run is manual and waited on. It must produce a 158/158 report before
scheduling is enabled:

```shell
gcloud run jobs execute retrostore-hourly-comparator \
  --project trs-80 \
  --region us-central1 \
  --wait
```

After that proof, Cloud Scheduler can call the Cloud Run v2 `jobs:run` endpoint
hourly with an OAuth token for the dedicated identity. The intended cron is
minute 17 of every hour in UTC. The exact resource command is kept out of an
apply script so service-account creation, prefix-scoped IAM, and scheduler
activation are reviewed together.

The checked-in Storage lifecycle deletes only comparison objects after 90 days.
The bucket's seven-day soft-delete policy provides a short recovery tail; it
does not change application-asset retention.

## Current private deployment

- Job: `retrostore-hourly-comparator`, `us-central1`
- Runtime identity: `retrostore-comparator@trs-80.iam.gserviceaccount.com`
- Image digest: `sha256:22d135c40f50ec10649f9a8480ad9898dbceb52a6c2628cbad1f73ac93bed3d4`
- Candidate: private `retrostore-api-compat-candidate`
- Retries: zero; timeout: 15 minutes; one task
- Schedule: minute 17 hourly, `Etc/UTC`, enabled

The first manual execution `retrostore-hourly-comparator-26mj6` completed
successfully on 2026-08-10. Its retained 26,470-byte report has SHA-256
`9cd14ec4ddb7278e668558d1695623389f83dd4f14e5ec1846225cf82bfe854c`
and matched 158/158 scenarios over 32 apps, 60 media objects, and 6,826,237
media bytes with no approval. The object exists only below the approved report
prefix. Bucket IAM is conditional on that prefix, and the applied lifecycle
matches only that prefix. Uniform bucket-level access, public-access prevention,
and seven-day soft delete remain enabled.

Cloud Scheduler then started execution `retrostore-hourly-comparator-tpl7s`
through the authenticated Cloud Run v2 job endpoint. It also matched 158/158
and retained the 26,470-byte report
`20260810T003533221691Z-f43d86a7e3f563c9.json`, whose full SHA-256 is
`f43d86a7e3f563c9063c0762ca2299ca45d01d850864ecd8964fe1c2bc4b3e66`.
Job generation 3 introduced download and website-list comparison. Generation 4
is now pinned to the four-surface comparator image; changing the private service
revision alone cannot silently change the comparator runtime. Each execution
requires the 158 frozen API scenarios, all dynamically discovered legacy
ZIP/typed downloads (currently 94), the full public website JSON list (currently
32 entries), and all six exact public redirects to pass in one schema-3
artifact. It derives download scenarios from public HTTP responses and needs no
catalog database or object-reader permission.

The checked-in `../front-door/private-soak-baseline.json` binds the current
private evidence clock to candidate revision `redirects1` and schema-3 evidence
beginning no earlier than 2026-08-10 03:55 UTC. The local
`retrostore.contract.soak_status` auditor verifies every retained object's
content digest and internal counts, checks that the expected revision still has
100% of private service traffic, and calculates continuity using the 90-minute
stale-evidence limit. Execution `retrostore-hourly-comparator-8n9n6` passed all
four surfaces and retained artifact
`20260810T035501395467Z-3c3d3bb30dec2e14.json` with full SHA-256
`3c3d3bb30dec2e148c7a635f7d928dc4a4e133238d6e8ba1dc1213b7c85da084`.
The first automatic generation-4 execution
`retrostore-hourly-comparator-28rck` then succeeded under the scheduler identity
and retained schema-3 artifact
`20260810T041828121946Z-c7f3d3c9581d2133.json`. The next hourly execution,
`retrostore-hourly-comparator-kcwrn`, also succeeded and retained artifact
`20260810T051927297893Z-d7fa173b8efc4bcd.json`, full SHA-256
`d7fa173b8efc4bcdda7187d4db162ec799e433b71907771e82be2026926b9b47`.
The auditor checksum-validated eleven reports total, with three current-boundary
reports and no continuity gap. The earlier schema-1 and schema-2 reports remain
valid history but cannot extend
this exact revision and schema-3 clock. The 14-day gate is current but not yet
eligible.

`runtime-baseline.json` independently pins job generation/image/configuration,
job invokers, the enabled UTC scheduler target and identity, and the private
report bucket's conditional writer and 90-day prefix lifecycle. The read-only
runtime auditor documented in `backend/README.md` passed all nine live checks on
2026-08-10. It emits neither environment values nor IAM members and has no
mutation operation.
This private clock is evidence only and does not authorize a hostname,
load balancer, data activation, or production route change.

References:

- [Execute Cloud Run jobs on a schedule](https://cloud.google.com/run/docs/execute/jobs-on-schedule)
- [Configure Cloud Run job commands](https://cloud.google.com/run/docs/configuring/jobs/containers)

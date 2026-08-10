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
- Image digest: `sha256:3a36e48a2a1f4a4a0952493099ffd1b229e96248bdba8d3c56228fb264b81310`
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
The job is now pinned to the hardened `observability2` API image; changing the
private service revision alone cannot silently change the comparator runtime.

References:

- [Execute Cloud Run jobs on a schedule](https://cloud.google.com/run/docs/execute/jobs-on-schedule)
- [Configure Cloud Run job commands](https://cloud.google.com/run/docs/configuring/jobs/containers)

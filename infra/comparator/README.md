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

References:

- [Execute Cloud Run jobs on a schedule](https://cloud.google.com/run/docs/execute/jobs-on-schedule)
- [Configure Cloud Run job commands](https://cloud.google.com/run/docs/configuring/jobs/containers)

# Cloud Run candidates

Replacement services are deployed in `us-central1`, a read/write region of the
approved `nam5` Firestore databases and the closest supported region for the
`US` multi-region buckets. Candidate services use dedicated runtime identities
and are not connected to the `retrostore.org` URL map.

The compatibility API image is built from `backend/` with
`services/api_compat/cloudbuild.yaml` and stored in the dedicated
`us-central1-docker.pkg.dev/trs-80/retrostore` repository. A candidate deploy
must set all replacement resource names explicitly:

```shell
gcloud run deploy retrostore-api-compat-candidate \
  --project trs-80 \
  --region us-central1 \
  --platform managed \
  --image IMAGE_DIGEST_OR_UNIQUE_TAG \
  --service-account retrostore-api@trs-80.iam.gserviceaccount.com \
  --set-env-vars \
    RETROSTORE_PROJECT=trs-80,RETROSTORE_CATALOG_DATABASE=retrostore,RETROSTORE_ASSETS_BUCKET=trs-80-retrostore-assets,RETROSTORE_STATE_DATABASE=retrostore-state,RETROSTORE_STATE_BUCKET=trs-80-retrostore-state \
  --memory 512Mi \
  --cpu 1 \
  --concurrency 20 \
  --min 0 \
  --max 2 \
  --invoker-iam-check \
  --no-allow-unauthenticated
```

Keep both privacy controls explicit. `--no-allow-unauthenticated` removes a
public invoker binding, while `--invoker-iam-check` ensures Cloud Run evaluates
the remaining service IAM policy on every request.

Grant the API identity permission to invoke only its private candidate service:

```shell
gcloud run services add-iam-policy-binding retrostore-api-compat-candidate \
  --project trs-80 \
  --region us-central1 \
  --member serviceAccount:retrostore-api@trs-80.iam.gserviceaccount.com \
  --role roles/run.invoker
```

Grant the active migration operator the same service-scoped role when using the
authenticated `gcloud run services proxy` command:

```shell
gcloud run services add-iam-policy-binding retrostore-api-compat-candidate \
  --project trs-80 \
  --region us-central1 \
  --member user:operator@example.com \
  --role roles/run.invoker
```

The exhaustive comparator can mint a short-lived identity token without
printing or writing it to disk:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python \
  -m retrostore.contract.exhaustive \
  --reference-url https://retrostore.org \
  --candidate-url PRIVATE_CANDIDATE_URL \
  --candidate-gcloud-identity-token-service-account \
    retrostore-api@trs-80.iam.gserviceaccount.com \
  --output /tmp/retrostore-cloud-comparison.json
```

The guarded state lifecycle probe is a dry run unless the exact candidate URL
is repeated as confirmation. It writes one synthetic 34-byte state, exercises
all three state RPCs, and never records the allocated token:

```shell
UV_CACHE_DIR=/tmp/retrostore-uv-cache uv run python \
  -m retrostore.contract.verify_http_state \
  --candidate-url PRIVATE_CANDIDATE_URL \
  --candidate-gcloud-identity-token-service-account \
    retrostore-api@trs-80.iam.gserviceaccount.com \
  --output /tmp/retrostore-cloud-state-http.json \
  --apply \
  --confirm-candidate-url PRIVATE_CANDIDATE_URL
```

The cloud candidate loads the catalog from the active durable snapshot and uses
the isolated state database/bucket for the three public state RPCs. The state
adapter enforces seven-day logical expiry before reads; Firestore TTL and the
eight-day bucket lifecycle remain asynchronous cleanup mechanisms.

## Current private candidate

- Service: `retrostore-api-compat-candidate`
- Region: `us-central1`
- Revision: `retrostore-api-compat-candidate-state1`
- Runtime identity: `retrostore-api@trs-80.iam.gserviceaccount.com`
- Image digest: `sha256:35cfa574d18696eb89aa2e99868938f9d7782541ff128fcd27dd10eb5da34ff4`
- Authentication: private; only the runtime identity and migration operator
  have service-scoped `roles/run.invoker`
- Production URL map: unchanged

The revision and container startup are healthy. The earlier broad 404 diagnosis
combined two causes: `/` was correctly absent in Flask, while Cloud Run reserves
some paths ending in `z` and intercepted the original `/healthz` route. The
candidate now uses `/health` and `/ready`. After explicitly enabling the invoker
IAM check, unauthenticated requests return HTTP 403. Both the temporary
public diagnostic and the final private, audience-bound identity run matched
all 158 read-only observations. The private authenticated HTTP state lifecycle
also passed upload, full download, memory-excluded download, and overlapping
region retrieval. No production routing changed.

## Current private administration candidate

- Service: `retrostore-admin-candidate`
- Region: `us-central1`
- Revision: `retrostore-admin-candidate-compact1`
- Runtime identity: `retrostore-admin@trs-80.iam.gserviceaccount.com`
- Image digest: `sha256:18d60af5803a168e3132b5315f345e10d9f5c14e7e949b0f206f601b241d836f`
- Authentication: private Cloud Run invocation followed by Firebase server
  session verification; no `allUsers` invoker binding
- Data mode: synchronized catalog read-only; Firestore user-profile roles and
  isolated top-level staging apps/authors/media/screenshots plus their atomic
  audit events are mutable
- Production URL map: unchanged

The authenticated runtime-identity smoke passed `/health`, `/ready`, the
Firebase login page, the compiled Tailwind asset, and the unauthenticated-to-
Firebase redirect. Google login, the explicit administrator claim, Firebase
session exchange, and browser inventory review then passed end to end through
the private proxy. The administrator-only user inventory uses Firebase's
read-only user permission. RetroStore role changes use the named Firestore
database, are re-checked on every request, and commit atomically with an audit
event; the runtime has no Firebase user-update permission. An unauthenticated
Cloud Run request returns HTTP 403. The service reads the same active
checksum-verified catalog snapshot as the public API candidate. The first
staging lifecycle writes only the future top-level `apps`, `authors`, and
`auditEvents` collections, with staged asset metadata in top-level `media` and
`screenshots`; it cannot alter the active versioned mirror. Staged edits and
asset ordering use optimistic revisions, deletions require explicit
confirmation, and every metadata mutation is atomically audited. Media and
screenshots use private checksum-addressed paths in the durable assets bucket;
replacement, individual deletion, and app cascade deletion clean up the old
objects. The post-deployment smoke reports all readiness checks healthy,
confirms the expected pre-session login redirect, and confirms that anonymous
Cloud Run invocation remains HTTP 403.

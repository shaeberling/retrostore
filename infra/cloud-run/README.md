# Cloud Run candidates

Replacement services are deployed in `us-central1`, a read/write region of the
approved `nam5` Firestore databases and the closest supported region for the
`US` multi-region buckets. Candidate services use dedicated runtime identities
and are not connected to the `retrostore.org` URL map.

The RetroStore Card and TRS-IO hardware update subsystem is not a Cloud Run
candidate. `/card`, `/card/*`, `/trs-io`, and `/trs-io/*`, including their
administration and Datastore-backed images, remain unchanged on App Engine. A
future production URL map must keep those route groups pinned to App Engine.

The compatibility API image is built from `backend/` with
`services/api_compat/cloudbuild.yaml` and stored in the dedicated
`us-central1-docker.pkg.dev/trs-80/retrostore` repository. The private comparison
service remains as documented below. The separately deployed final service is
`retrostore-api-next`; it has load-balancer-only ingress, a disabled default
URL, and is reachable only through the `retrostore-next` load balancer. Both
deployments set all replacement resource names explicitly:

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
- Revision: `retrostore-api-compat-candidate-redirects1`
- Runtime identity: `retrostore-api@trs-80.iam.gserviceaccount.com`
- Image digest: `sha256:22d135c40f50ec10649f9a8480ad9898dbceb52a6c2628cbad1f73ac93bed3d4`
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

Revision `observability1` added bounded JSON request events without URLs, query
strings, client addresses, user agents, tokens, cookies, identities, request
bodies, or response bodies. The zero-traffic revision passed health/readiness,
anonymous HTTP 403, the real JVM/KMP/embedded-C consumer harness, and the full
158/158 production comparison before receiving 100% of private candidate
traffic. Cloud Logging parsed its `httpRequest` fields, service/API labels, and
Cloud Trace correlation as structured fields.

Revision `observability2` hardens the API-method label: a request whose path is
not one of the nine frozen API methods is recorded only as `unknown`, never as
attacker-controlled path text. It passed the same health, denial, consumer, and
158/158 zero-traffic gates before receiving 100% of private candidate traffic.

Revision `downloads1` adds the public read-only `/downloadapp` compatibility
handler over the immutable normalized mirror. Before private promotion it denied
anonymous invocation, matched all 94 current ZIP/typed/error download scenarios,
matched the frozen API corpus 158/158 with zero approvals, and passed a guarded
synthetic lifecycle through all three state RPCs. It then received 100% of the
private candidate traffic; `retrostore.org` and the active catalog pointer did
not change. A manual 158/158 comparator seeded its new revision-bound evidence streak.
Two subsequent concurrency-8 runs each matched 2,000/2,000 frozen API
responses. The first preserved a low-sample client-latency non-pass while
exact-revision resource telemetry passed; the independent confirmation passed
all provisional method gates at 38.08 requests per second. No service setting
changed during either run.

Revision `website1` adds the mirror-generated `/public/apps.json` dependency for
the static website. At zero traffic it denied anonymous access, matched all 32
legacy `pubapplist` entries, matched all 94 download scenarios and all 158
frozen API scenarios, and passed the isolated synthetic state lifecycle. It
then received 100% of the private candidate traffic. The scheduled and manual
comparators independently matched 158/158 immediately afterward; production
routing, IAM, service limits, and the active catalog pointer did not change.

Revision `redirects1` adds the six exact `/community[/]`, `/rsc[/]`, and
`/app[/]` website redirects with the legacy empty-body 302 responses. At zero
traffic it denied anonymous invocation and passed API 158/158, downloads 94/94,
website catalog 32/32, redirects 6/6, and the guarded synthetic state lifecycle.
It now receives 100% of only the private candidate traffic. The prior tagged
revisions remain available at zero traffic, the invoker policy is unchanged,
and no production route or catalog pointer moved.

The current revision also passed the deployed real-client gate through a
temporary authenticated loopback proxy. The published JVM SDK exercised all
nine methods, the pinned TRS-80 KMP client exercised its five methods, and the
pinned embedded C client exercised its three legacy-JSON/nanopb methods. The
native fixture now finds its reviewed media app through the client's own
pagination instead of assuming a representative-only catalog position. The two
managed clients used isolated synthetic states; the retained result exposes no
tokens or payloads. The temporary proxy was stopped after the passing run.

## Private staged-snapshot preview

- Service: `retrostore-api-preview`
- Region: `us-central1`
- Revision: `retrostore-api-preview-preview1`
- Runtime identity: `retrostore-api@trs-80.iam.gserviceaccount.com`
- Image digest: `sha256:1f265510a590a6a880b759626dfb94d6106c43aa2c8590963f1825b7c60aaeee`
- Pinned snapshot: `catalog-5b0bbf8bb683ed653d4583fa486589358ea759ff0e145f156bedb049b7cc04a2`
- Authentication: private; only the runtime identity and migration operator
  have service-scoped `roles/run.invoker`; anonymous HTTP returns 403
- Production URL map: unchanged

This is a separate service, not a revision receiving traffic on the active
candidate. Both the snapshot ID and digest are explicit environment variables,
and startup reconciles the complete staged manifest. The 2026-08-10 exhaustive
run matched 156/158 production scenarios. The two expected differences were
the full and nano catalog pages, each adding only isolated staged `TestApp`
(`015488ef-d9e2-4437-9c38-519d10cb8585`) and removing nothing. All existing
app details, media responses, and media ranges matched. The synthetic external
state lifecycle also passed all checks. The active snapshot pointer and
production routing did not move.

## Current private administration candidate

- Service: `retrostore-admin-candidate`
- Region: `us-central1`
- Revision: `retrostore-admin-candidate-observability1`
- Runtime identity: `retrostore-admin@trs-80.iam.gserviceaccount.com`
- Image digest: `sha256:5ea9ffe42bad43e374c3cc38e12e4d9716a6d1870e83320cde59bb337e150c84`
- Authentication: private Cloud Run invocation followed by Firebase server
  session verification; no `allUsers` invoker binding
- Data mode: the materialized synchronized baseline is read-only; Firestore
  user-profile roles, isolated `STAGING` records, guarded RPK imports, and
  copy-on-write published drafts plus their draft-only assets are mutable
- Production URL map: unchanged

The checked-in `private-candidate-baseline.json` pins this service, the active
API candidate, and the publication preview. Run the read-only drift auditor
documented in `backend/README.md` after any deployment or IAM change. Its
2026-08-10 live run passed all three services: exact revision, image, runtime
configuration, one 100% traffic target, exact invoker sets, no public principal,
and anonymous HTTP 403. It emits no environment values or member identities and
cannot modify a service or policy.

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
Cloud Run invocation remains HTTP 403. The authenticated end-to-end staged asset
lifecycle passed on 2026-08-09. Read-only reconciliation verified the live
intermediate references and object bytes, superseded-media cleanup, individual
and cascade deletion, nine retained audit events, and zero remaining staged
documents or object-prefix entries. A subsequent deployed 158-scenario public
API comparison had zero differences.

Revision `rpk1` adds the preview-first legacy RPK workflow. The initial package
upload is validated and discarded without writes; apply requires a second
upload with the exact previewed SHA-256. It preserves the package app ID, binds
ownership to the signed-in Firebase identity, refuses staged collisions, and
commits all imported metadata with one audit event. Final asset objects are
removed if the transaction fails. Deployment smoke checks passed `/health`, all
six `/ready` checks, the Firebase login page, the pre-session import redirect,
100% private-candidate traffic on the expected digest, and anonymous HTTP 403.
The authenticated browser lifecycle passed on 2026-08-09. A disposable package
first produced only a validated preview. Applying its exact SHA-256-matched
re-upload created revision 1 with two ordered media documents, one screenshot,
three checksum-verified objects totaling 120 bytes, and one import audit event.
The complete public corpus still matched 158/158. Confirmed UI deletion then
removed every staged document and object while retaining the import and delete
audit events; a second post-cleanup public comparison also matched 158/158 with
zero approvals or differences. Production routing and the active synchronized
snapshot are unchanged.

Revision `working1` adds the materialized working-catalog view and enforces its
`PUBLISHED` baseline as read-only in both service methods and rendered UI. It
supports the exact legacy application, media, and screenshot identifier forms
and normalized extensionless screenshot paths without granting Firebase
ownership from legacy email. All six readiness checks, login/CSS smoke tests,
pre-session redirect, private IAM, and anonymous HTTP 403 passed. The dedicated
migrator atomically materialized 32 apps, 18 authors, 60 media records, and 90
screenshots. A follow-up reconciled all 200 documents, source fingerprints,
active object checksums, control metadata, and exactly one audit event. The
active snapshot pointer did not move, and the post-materialization public
comparison matched 158/158 with zero differences.

Revision `draft1` added audited copy-on-write metadata overlays in the separate
`appDrafts` collection, bound to the exact baseline snapshot and source
fingerprint. Revision `draft2` extends those overlays to media and screenshots
through separate `appDraftMedia` and `appDraftScreenshots` collections.
Replacing or removing an inherited asset changes only the overlay and never
deletes a published object; draft-only uploads use unique immutable paths and
are deleted when replaced, removed, or discarded. The responsive compact slot
rows and ordered screenshot controls are shared with new-app staging. `draft2`
passed all seven readiness checks, login/CSS/redirect smoke tests at zero
percent before receiving 100% of private admin traffic. Anonymous HTTP remains
403. A subsequent active-snapshot comparison matched 158/158 with no approvals.
No authenticated draft asset mutation was created automatically during the
deployment smoke, so the existing isolated staged `TestApp` was left unchanged.

Revision `observability1` retains all `draft2` behavior and adds the same
privacy-safe request events. It passed all seven readiness checks, login,
compiled CSS, pre-session redirect, structured-log parsing and trace
correlation, and anonymous HTTP 403 at zero traffic before receiving 100% of
private admin traffic. The earlier `draft1` and `draft2` tags remain at zero
percent for private rollback.

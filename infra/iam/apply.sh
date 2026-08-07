#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="trs-80"
APPLY=false
CONFIRM_PROJECT=""
OPERATOR_MEMBER=""

usage() {
  echo "Usage: $0 [--apply --confirm-project trs-80] [--operator-member user:email]" >&2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)
      APPLY=true
      shift
      ;;
    --confirm-project)
      CONFIRM_PROJECT="${2:-}"
      shift 2
      ;;
    --operator-member)
      OPERATOR_MEMBER="${2:-}"
      shift 2
      ;;
    *)
      usage
      exit 2
      ;;
  esac
done

if [[ "$APPLY" == true && "$CONFIRM_PROJECT" != "$PROJECT_ID" ]]; then
  echo "Refusing to apply: --confirm-project must equal $PROJECT_ID" >&2
  exit 2
fi

if [[ -n "$OPERATOR_MEMBER" && ! "$OPERATOR_MEMBER" =~ ^(user|group|serviceAccount):.+$ ]]; then
  echo "Refusing invalid --operator-member: $OPERATOR_MEMBER" >&2
  exit 2
fi

MIGRATOR="retrostore-migrator@${PROJECT_ID}.iam.gserviceaccount.com"
API_RUNTIME="retrostore-api@${PROJECT_ID}.iam.gserviceaccount.com"
ADMIN_RUNTIME="retrostore-admin@${PROJECT_ID}.iam.gserviceaccount.com"
ADMIN_SESSION_ROLE="retrostoreAdminSessionIssuer"

run() {
  if [[ "$APPLY" == true ]]; then
    "$@"
  else
    printf 'DRY RUN:'
    printf ' %q' "$@"
    printf '\n'
  fi
}

ensure_service_account() {
  local account_id="$1"
  local display_name="$2"
  local description="$3"
  local email="${account_id}@${PROJECT_ID}.iam.gserviceaccount.com"

  if [[ "$APPLY" == true ]] && gcloud iam service-accounts describe "$email" \
    --project="$PROJECT_ID" --quiet >/dev/null 2>&1; then
    return
  fi

  run gcloud iam service-accounts create "$account_id" \
    --project="$PROJECT_ID" \
    --display-name="$display_name" \
    --description="$description" \
    --quiet
}

ensure_custom_role() {
  local role_id="$1"
  local title="$2"
  local description="$3"
  local permissions="$4"

  if [[ "$APPLY" == true ]] && gcloud iam roles describe "$role_id" \
    --project="$PROJECT_ID" --quiet >/dev/null 2>&1; then
    run gcloud iam roles update "$role_id" \
      --project="$PROJECT_ID" \
      --title="$title" \
      --description="$description" \
      --permissions="$permissions" \
      --stage=GA \
      --quiet
    return
  fi

  run gcloud iam roles create "$role_id" \
    --project="$PROJECT_ID" \
    --title="$title" \
    --description="$description" \
    --permissions="$permissions" \
    --stage=GA \
    --quiet
}

grant_database_role() {
  local member="$1"
  local role="$2"
  local database="$3"
  local title="$4"

  run gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${member}" \
    --role="$role" \
    --condition="expression=resource.name == \"projects/${PROJECT_ID}/databases/${database}\",title=${title},description=Restrict RetroStore access to the named database" \
    --quiet
}

grant_bucket_role() {
  local member="$1"
  local role="$2"
  local bucket="$3"

  run gcloud storage buckets add-iam-policy-binding "gs://${bucket}" \
    --member="serviceAccount:${member}" \
    --role="$role" \
    --project="$PROJECT_ID" \
    --quiet
}

ensure_service_account \
  "retrostore-migrator" \
  "RetroStore catalog migrator" \
  "Keyless identity for guarded imports into isolated replacement catalog storage"
ensure_service_account \
  "retrostore-api" \
  "RetroStore compatibility API" \
  "Cloud Run identity for the public compatibility API"
ensure_service_account \
  "retrostore-admin" \
  "RetroStore administration" \
  "Cloud Run identity for the server-rendered administration service"
ensure_custom_role \
  "$ADMIN_SESSION_ROLE" \
  "RetroStore admin session issuer" \
  "Create Firebase session cookies and check user revocation without user-management access" \
  "firebaseauth.users.createSession,firebaseauth.users.get"

grant_database_role "$MIGRATOR" roles/datastore.user retrostore retrostore_migrator_catalog
grant_bucket_role "$MIGRATOR" roles/storage.objectCreator trs-80-retrostore-assets
grant_bucket_role "$MIGRATOR" roles/storage.objectViewer trs-80-retrostore-assets

grant_database_role "$API_RUNTIME" roles/datastore.viewer retrostore retrostore_api_catalog_read
grant_database_role "$API_RUNTIME" roles/datastore.user retrostore-state retrostore_api_state
grant_bucket_role "$API_RUNTIME" roles/storage.objectViewer trs-80-retrostore-assets
grant_bucket_role "$API_RUNTIME" roles/storage.objectAdmin trs-80-retrostore-state

grant_database_role "$ADMIN_RUNTIME" roles/datastore.user retrostore retrostore_admin_catalog
grant_bucket_role "$ADMIN_RUNTIME" roles/storage.objectAdmin trs-80-retrostore-assets
run gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${ADMIN_RUNTIME}" \
  --role="projects/${PROJECT_ID}/roles/${ADMIN_SESSION_ROLE}" \
  --condition=None \
  --quiet

if [[ -n "$OPERATOR_MEMBER" ]]; then
  run gcloud iam service-accounts add-iam-policy-binding "$MIGRATOR" \
    --member="$OPERATOR_MEMBER" \
    --role=roles/iam.serviceAccountTokenCreator \
    --project="$PROJECT_ID" \
    --quiet
  run gcloud iam service-accounts add-iam-policy-binding "$API_RUNTIME" \
    --member="$OPERATOR_MEMBER" \
    --role=roles/iam.serviceAccountUser \
    --project="$PROJECT_ID" \
    --quiet
  run gcloud iam service-accounts add-iam-policy-binding "$API_RUNTIME" \
    --member="$OPERATOR_MEMBER" \
    --role=roles/iam.serviceAccountTokenCreator \
    --project="$PROJECT_ID" \
    --quiet
  run gcloud iam service-accounts add-iam-policy-binding "$ADMIN_RUNTIME" \
    --member="$OPERATOR_MEMBER" \
    --role=roles/iam.serviceAccountUser \
    --project="$PROJECT_ID" \
    --quiet
  run gcloud iam service-accounts add-iam-policy-binding "$ADMIN_RUNTIME" \
    --member="$OPERATOR_MEMBER" \
    --role=roles/iam.serviceAccountTokenCreator \
    --project="$PROJECT_ID" \
    --quiet
fi

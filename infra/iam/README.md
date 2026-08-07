# RetroStore workload IAM

`apply.sh` creates three keyless service accounts and adds only additive,
resource-scoped bindings. It does not replace a project or bucket IAM policy.
The script is a dry run unless `--apply` and the exact project confirmation are
both supplied.

| Identity | Firestore | Cloud Storage |
| --- | --- | --- |
| `retrostore-migrator` | `roles/datastore.user` on `retrostore` only | create/read objects in `trs-80-retrostore-assets` |
| `retrostore-api` | read `retrostore`; read/write `retrostore-state` | read assets; manage state objects |
| `retrostore-admin` | read/write `retrostore`; no state access | manage durable assets; no state-bucket access |

The admin identity also receives the project custom role
`retrostoreAdminSessionIssuer`, containing only
`firebaseauth.users.createSession` and `firebaseauth.users.get`. Those are the
permissions required to exchange a recently verified ID token for a Firebase
session cookie, check revocation, and inspect users. RetroStore roles are stored
in the named Firestore database and re-checked on every protected request, so
the runtime does not receive Firebase user-update, creation, deletion, or
provider-configuration access. Role and audit documents are written atomically
after administrator authorization and CSRF validation.

Firestore predefined data roles are granted on the project with an IAM
condition that exactly matches one named database. This prevents the workload
identities from accessing the legacy `(default)` Datastore-mode database.
Storage roles are attached directly to the approved replacement buckets.

Preview the commands:

```shell
./infra/iam/apply.sh
```

Apply them, optionally allowing one operator to impersonate the migrator and
deploy the runtime identities without downloading service-account keys:

```shell
./infra/iam/apply.sh \
  --apply \
  --confirm-project trs-80 \
  --operator-member user:operator@example.com
```

The operator bindings are on each individual service-account resource, not the
project. The operator may mint short-lived tokens for the migrator and both
candidate runtime identities and may deploy both services. The migration CLI
additionally rejects any impersonated identity other than
`retrostore-migrator@trs-80.iam.gserviceaccount.com`.

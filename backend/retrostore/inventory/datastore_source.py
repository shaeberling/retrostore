"""Read-only Google Cloud Datastore source adapter."""

import subprocess
from collections.abc import Iterable

from google.cloud import datastore
from google.oauth2.credentials import Credentials

from retrostore.inventory.report import SourceEntity


class DatastoreSource:
    """Fetch entities through queries; this adapter exposes no mutation methods."""

    def __init__(self, client: datastore.Client) -> None:
        self._client = client

    def fetch_kind(self, kind: str) -> Iterable[SourceEntity]:
        query = self._client.query(kind=kind)
        for entity in query.fetch():
            yield SourceEntity(kind=kind, key=entity.key, properties=entity)


def create_datastore_source(
    *, project: str, database: str, auth: str = "adc"
) -> DatastoreSource:
    credentials = None
    if auth == "gcloud":
        credentials = gcloud_credentials(quota_project=project)
    elif auth != "adc":
        raise ValueError(f"Unsupported authentication mode: {auth}")

    client_database = "" if database == "(default)" else database
    client = datastore.Client(project=project, database=client_database, credentials=credentials)
    return DatastoreSource(client)


def gcloud_credentials(*, quota_project: str | None = None) -> Credentials:
    """Return the current gcloud user's short-lived token without logging it."""

    completed = subprocess.run(
        ["gcloud", "auth", "print-access-token"],
        check=True,
        capture_output=True,
        text=True,
    )
    token = completed.stdout.strip()
    if not token:
        raise RuntimeError("gcloud returned an empty access token")
    return Credentials(token=token, quota_project_id=quota_project)

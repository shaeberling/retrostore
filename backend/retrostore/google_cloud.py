"""Shared Google Cloud authentication helpers."""

import subprocess

from google.oauth2.credentials import Credentials as AccessTokenCredentials


def gcloud_impersonated_credentials(
    *, project: str, service_account: str
) -> AccessTokenCredentials:
    """Mint a short-lived operator token without creating a service-account key."""

    try:
        completed = subprocess.run(
            [
                "gcloud",
                "auth",
                "print-access-token",
                f"--impersonate-service-account={service_account}",
                f"--project={project}",
                "--quiet",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or "gcloud exited unsuccessfully"
        raise RuntimeError(f"Could not impersonate {service_account}: {detail}") from None
    token = completed.stdout.strip()
    if not token:
        raise RuntimeError("gcloud returned an empty impersonated access token")
    return AccessTokenCredentials(token=token)

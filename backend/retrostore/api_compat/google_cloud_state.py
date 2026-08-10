"""Google Cloud adapters for isolated, expiring public state persistence."""

import hashlib
import re
import secrets
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

from google.api_core.exceptions import NotFound, PreconditionFailed
from google.auth.credentials import Credentials
from google.cloud import firestore, storage

from retrostore.api_compat.state_persistence import (
    PersistentStateStorage,
    StatePayloadReference,
    StateTokenRecord,
)
from retrostore.mirror.google_cloud import gcloud_impersonated_credentials

_SHA256 = re.compile(r"[0-9a-f]{64}")
_MIN_TOKEN = 100
_MAX_TOKEN = 999


class CloudStatePayloadStore:
    """Create unique immutable protobuf payloads in the private state bucket."""

    def __init__(
        self,
        bucket: storage.Bucket,
        *,
        object_id: Callable[[], str] | None = None,
    ) -> None:
        self._bucket = bucket
        self._object_id = object_id or (lambda: uuid.uuid4().hex)

    def create(self, body: bytes, sha256: str) -> StatePayloadReference:
        if _SHA256.fullmatch(sha256) is None:
            raise ValueError("State payload SHA-256 is malformed")
        if hashlib.sha256(body).hexdigest() != sha256:
            raise ValueError("State payload body does not match its SHA-256")

        for _ in range(3):
            path = f"states/{self._object_id()}/{sha256}.pb"
            _validate_payload_path(path)
            blob = self._bucket.blob(path)
            blob.metadata = {"sha256": sha256}
            try:
                blob.upload_from_string(
                    body,
                    content_type="application/x-protobuf",
                    checksum="auto",
                    if_generation_match=0,
                )
            except PreconditionFailed:
                continue
            generation = blob.generation
            if not isinstance(generation, int) or generation <= 0:
                raise ValueError("Cloud Storage did not return a state object generation")
            return StatePayloadReference(path, generation, len(body), sha256)
        raise RuntimeError("Could not allocate a unique state object path")

    def read(self, value: StatePayloadReference) -> bytes:
        try:
            return bytes(
                self._bucket.blob(value.path).download_as_bytes(
                    checksum="auto",
                    if_generation_match=value.generation,
                )
            )
        except (NotFound, PreconditionFailed) as error:
            raise ValueError("State payload is missing or its generation changed") from error

    def delete(self, value: StatePayloadReference) -> None:
        try:
            self._bucket.blob(value.path).delete(if_generation_match=value.generation)
        except NotFound:
            return
        except PreconditionFailed as error:
            raise ValueError("Refusing to delete a changed state payload") from error


@dataclass(frozen=True, slots=True)
class _ClaimAttempt:
    claimed: bool
    replaced: StatePayloadReference | None = None


class FirestoreStateTokenStore:
    """Claim legacy 100-999 tokens transactionally in the isolated state database."""

    def __init__(
        self,
        client: firestore.Client,
        *,
        token_order: Callable[[], Iterable[int]] | None = None,
    ) -> None:
        self._client = client
        self._token_order = token_order or _random_token_order

    def claim(
        self,
        payload: StatePayloadReference,
        *,
        created_at: datetime,
        expires_at: datetime,
    ) -> tuple[int, StatePayloadReference | None]:
        _validate_timestamps(created_at, expires_at)
        seen: set[int] = set()
        for token in self._token_order():
            if token in seen or not _MIN_TOKEN <= token <= _MAX_TOKEN:
                raise ValueError("State token candidates must be unique values from 100 to 999")
            seen.add(token)
            reference = self._client.collection("states").document(str(token))

            @firestore.transactional
            def try_claim(
                transaction: Any,
                reference: Any = reference,
                token: int = token,
            ) -> _ClaimAttempt:
                snapshot = reference.get(transaction=transaction)
                replaced = None
                if snapshot.exists:
                    existing = _token_record(snapshot, token)
                    if existing.expires_at > created_at:
                        return _ClaimAttempt(False)
                    replaced = existing.payload
                transaction.set(
                    reference,
                    _token_document(payload, created_at=created_at, expires_at=expires_at),
                )
                return _ClaimAttempt(True, replaced)

            attempt = try_claim(self._client.transaction())
            if attempt.claimed:
                return token, attempt.replaced
        raise RuntimeError("No state token is available")

    def get(self, token: int, *, now: datetime) -> StateTokenRecord | None:
        if not _MIN_TOKEN <= token <= _MAX_TOKEN:
            return None
        snapshot = self._client.collection("states").document(str(token)).get()
        if not snapshot.exists:
            return None
        record = _token_record(snapshot, token)
        return record if record.expires_at > now else None

    def list_live(self, *, now: datetime) -> tuple[StateTokenRecord, ...]:
        """Return every logically live token after validating the complete collection."""

        records: list[StateTokenRecord] = []
        seen: set[int] = set()
        for snapshot in self._client.collection("states").stream():
            token = _token_document_id(snapshot.id)
            if token in seen:
                raise ValueError("State token collection contains a duplicate token")
            seen.add(token)
            record = _token_record(snapshot, token)
            if record.expires_at > now:
                records.append(record)
        return tuple(sorted(records, key=lambda value: value.token))


def google_state_storage(
    *,
    project: str,
    database: str,
    bucket: str,
    impersonate_service_account: str | None = None,
    credentials: Credentials | None = None,
) -> PersistentStateStorage:
    payloads, tokens = google_state_stores(
        project=project,
        database=database,
        bucket=bucket,
        impersonate_service_account=impersonate_service_account,
        credentials=credentials,
    )
    return PersistentStateStorage(payloads, tokens)


def google_state_stores(
    *,
    project: str,
    database: str,
    bucket: str,
    impersonate_service_account: str | None = None,
    credentials: Credentials | None = None,
) -> tuple[CloudStatePayloadStore, FirestoreStateTokenStore]:
    """Construct the independently usable state payload and token stores."""

    validate_state_target(project=project, database=database, bucket=bucket)
    if impersonate_service_account is not None:
        if credentials is not None:
            raise ValueError("Pass credentials or impersonation, not both")
        validate_state_identity(project, impersonate_service_account)
        credentials = gcloud_impersonated_credentials(
            project=project,
            service_account=impersonate_service_account,
        )
    firestore_client = firestore.Client(
        project=project,
        database=database,
        credentials=credentials,
    )
    storage_bucket = storage.Client(project=project, credentials=credentials).bucket(bucket)
    return (
        CloudStatePayloadStore(storage_bucket),
        FirestoreStateTokenStore(firestore_client),
    )


def validate_state_target(*, project: str, database: str, bucket: str) -> None:
    if not project:
        raise ValueError("State project must be explicit")
    if database != "retrostore-state":
        raise ValueError("State persistence must target the isolated retrostore-state database")
    if bucket != f"{project}-retrostore-state":
        raise ValueError("State persistence must target the isolated project state bucket")


def state_service_account(project: str) -> str:
    return f"retrostore-api@{project}.iam.gserviceaccount.com"


def validate_state_identity(project: str, service_account: str) -> None:
    if service_account != state_service_account(project):
        raise ValueError("State access must impersonate the project API runtime identity")


def _random_token_order() -> tuple[int, ...]:
    values = list(range(_MIN_TOKEN, _MAX_TOKEN + 1))
    secrets.SystemRandom().shuffle(values)
    return tuple(values)


def _token_document(
    payload: StatePayloadReference,
    *,
    created_at: datetime,
    expires_at: datetime,
) -> dict[str, Any]:
    return {
        "objectPath": payload.path,
        "objectGeneration": payload.generation,
        "size": payload.size,
        "sha256": payload.sha256,
        "createdAt": created_at,
        "expiresAt": expires_at,
    }


def _token_record(snapshot: Any, token: int) -> StateTokenRecord:
    value = snapshot.to_dict()
    if not isinstance(value, dict):
        raise ValueError("State token document is malformed")
    path = value.get("objectPath")
    digest = value.get("sha256")
    created_at = value.get("createdAt")
    expires_at = value.get("expiresAt")
    if not isinstance(path, str):
        raise ValueError("State token objectPath is malformed")
    _validate_payload_path(path)
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise ValueError("State token sha256 is malformed")
    if not isinstance(created_at, datetime) or not isinstance(expires_at, datetime):
        raise ValueError("State token timestamps are malformed")
    _validate_timestamps(created_at, expires_at)
    generation = _integer(value.get("objectGeneration"), "objectGeneration", minimum=1)
    size = _integer(value.get("size"), "size", minimum=0)
    return StateTokenRecord(
        token=token,
        payload=StatePayloadReference(path, generation, size, digest),
        created_at=created_at,
        expires_at=expires_at,
    )


def _integer(value: object, name: str, *, minimum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"State token {name} is malformed")
    return value


def _token_document_id(value: object) -> int:
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        raise ValueError("State token document ID is malformed")
    token = int(value)
    if str(token) != value or not _MIN_TOKEN <= token <= _MAX_TOKEN:
        raise ValueError("State token document ID is malformed")
    return token


def _validate_timestamps(created_at: datetime, expires_at: datetime) -> None:
    if (
        created_at.tzinfo is None
        or created_at.utcoffset() is None
        or expires_at.tzinfo is None
        or expires_at.utcoffset() is None
        or expires_at <= created_at
    ):
        raise ValueError("State token timestamps must be aware and increasing")


def _validate_payload_path(path: str) -> None:
    parsed = PurePosixPath(path)
    if (
        not path.startswith("states/")
        or "\\" in path
        or parsed.is_absolute()
        or path != parsed.as_posix()
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise ValueError("State payload path is not normalized")

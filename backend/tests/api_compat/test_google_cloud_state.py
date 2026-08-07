import hashlib
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from google.api_core.exceptions import NotFound, PreconditionFailed

from retrostore.api_compat.google_cloud_state import (
    CloudStatePayloadStore,
    FirestoreStateTokenStore,
    validate_state_target,
)
from retrostore.api_compat.state_persistence import StatePayloadReference


class FakeBlob:
    def __init__(self, bucket: FakeBucket, name: str) -> None:
        self._bucket = bucket
        self.name = name
        self.metadata: dict[str, str] | None = None
        self.generation: int | None = None

    def upload_from_string(self, body: bytes, **kwargs: Any) -> None:
        self._bucket.upload_kwargs.append(kwargs)
        if self.name in self._bucket.objects:
            raise PreconditionFailed("exists")
        generation = self._bucket.next_generation
        self._bucket.next_generation += 1
        self._bucket.objects[self.name] = (generation, bytes(body))
        self.generation = generation

    def download_as_bytes(self, **kwargs: Any) -> bytes:
        try:
            generation, body = self._bucket.objects[self.name]
        except KeyError as error:
            raise NotFound("missing") from error
        if kwargs.get("if_generation_match") != generation:
            raise PreconditionFailed("changed")
        return body

    def delete(self, **kwargs: Any) -> None:
        try:
            generation, _ = self._bucket.objects[self.name]
        except KeyError as error:
            raise NotFound("missing") from error
        if kwargs.get("if_generation_match") != generation:
            raise PreconditionFailed("changed")
        del self._bucket.objects[self.name]


class FakeBucket:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[int, bytes]] = {}
        self.upload_kwargs: list[dict[str, Any]] = []
        self.next_generation = 1

    def blob(self, name: str) -> FakeBlob:
        return FakeBlob(self, name)


class FakeSnapshot:
    def __init__(self, document_id: str, data: dict[str, Any] | None) -> None:
        self.id = document_id
        self.exists = data is not None
        self._data = deepcopy(data)

    def to_dict(self) -> dict[str, Any] | None:
        return deepcopy(self._data)


class FakeDocument:
    def __init__(self, client: FakeClient, document_id: str) -> None:
        self._client = client
        self.id = document_id

    def get(self, **kwargs: Any) -> FakeSnapshot:
        return FakeSnapshot(self.id, self._client.documents.get(self.id))


class FakeCollection:
    def __init__(self, client: FakeClient) -> None:
        self._client = client

    def document(self, document_id: str) -> FakeDocument:
        return FakeDocument(self._client, document_id)


class FakeTransaction:
    def __init__(self, client: FakeClient) -> None:
        self._client = client

    def set(self, document: FakeDocument, value: dict[str, Any]) -> None:
        self._client.documents[document.id] = deepcopy(value)


class FakeClient:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}

    def collection(self, name: str) -> FakeCollection:
        assert name == "states"
        return FakeCollection(self)

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(self)


def _payload(name: str = "new", generation: int = 2) -> StatePayloadReference:
    return StatePayloadReference(
        f"states/{name}/{'a' * 64}.pb",
        generation,
        3,
        "a" * 64,
    )


def _document(
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


def test_state_payloads_are_unique_create_only_and_generation_guarded() -> None:
    bucket = FakeBucket()
    object_ids = iter(("collision", "created"))
    body = b"abc"
    digest = hashlib.sha256(body).hexdigest()
    bucket.objects[f"states/collision/{digest}.pb"] = (7, b"older")
    store = CloudStatePayloadStore(  # type: ignore[arg-type]
        bucket,
        object_id=lambda: next(object_ids),
    )

    reference = store.create(body, digest)

    assert reference == StatePayloadReference(
        f"states/created/{digest}.pb",
        1,
        3,
        digest,
    )
    assert store.read(reference) == body
    assert bucket.upload_kwargs[-1]["if_generation_match"] == 0
    assert bucket.upload_kwargs[-1]["checksum"] == "auto"

    store.delete(reference)
    with pytest.raises(ValueError, match="missing or its generation changed"):
        store.read(reference)


def test_state_tokens_skip_live_values_and_reuse_expired_values_transactionally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "retrostore.api_compat.google_cloud_state.firestore.transactional",
        lambda function: function,
    )
    now = datetime(2026, 8, 7, 13, tzinfo=UTC)
    old = _payload("old", 1)
    client = FakeClient()
    client.documents["100"] = _document(
        old,
        created_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=1),
    )
    store = FirestoreStateTokenStore(  # type: ignore[arg-type]
        client,
        token_order=lambda: (100, 101),
    )

    token, replaced = store.claim(
        _payload(),
        created_at=now,
        expires_at=now + timedelta(days=7),
    )

    assert token == 101
    assert replaced is None
    assert store.get(101, now=now) is not None

    client.documents["100"]["expiresAt"] = now
    replacing_store = FirestoreStateTokenStore(  # type: ignore[arg-type]
        client,
        token_order=lambda: (100,),
    )
    token, replaced = replacing_store.claim(
        _payload("replacement", 3),
        created_at=now,
        expires_at=now + timedelta(days=7),
    )

    assert token == 100
    assert replaced == old
    assert client.documents["100"]["objectPath"].startswith("states/replacement/")


def test_state_tokens_enforce_logical_expiry_and_candidate_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "retrostore.api_compat.google_cloud_state.firestore.transactional",
        lambda function: function,
    )
    now = datetime(2026, 8, 7, 13, tzinfo=UTC)
    client = FakeClient()
    client.documents["123"] = _document(
        _payload(),
        created_at=now - timedelta(days=7),
        expires_at=now,
    )
    store = FirestoreStateTokenStore(  # type: ignore[arg-type]
        client,
        token_order=lambda: (99,),
    )

    assert store.get(123, now=now) is None
    with pytest.raises(ValueError, match="100 to 999"):
        store.claim(
            _payload(),
            created_at=now,
            expires_at=now + timedelta(days=7),
        )


def test_state_targets_are_exact_and_cannot_fall_back_to_legacy_resources() -> None:
    validate_state_target(
        project="trs-80",
        database="retrostore-state",
        bucket="trs-80-retrostore-state",
    )
    with pytest.raises(ValueError, match="isolated retrostore-state database"):
        validate_state_target(
            project="trs-80",
            database="(default)",
            bucket="trs-80-retrostore-state",
        )
    with pytest.raises(ValueError, match="isolated project state bucket"):
        validate_state_target(
            project="trs-80",
            database="retrostore-state",
            bucket="trs-80.appspot.com",
        )

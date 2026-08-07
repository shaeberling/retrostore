import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from retrostore.api_compat.state_persistence import (
    PersistentStateStorage,
    StatePayloadReference,
    StateTokenRecord,
)
from retrostore.generated import ApiProtos_pb2 as api_pb


class MemoryPayloadStore:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, int], bytes] = {}
        self.deleted: list[StatePayloadReference] = []
        self.fail_delete = False

    def create(self, body: bytes, sha256: str) -> StatePayloadReference:
        generation = len(self.objects) + 1
        value = StatePayloadReference(
            f"states/object-{generation}/{sha256}.pb",
            generation,
            len(body),
            sha256,
        )
        self.objects[(value.path, value.generation)] = bytes(body)
        return value

    def read(self, value: StatePayloadReference) -> bytes:
        return self.objects[(value.path, value.generation)]

    def delete(self, value: StatePayloadReference) -> None:
        if self.fail_delete:
            raise RuntimeError("injected delete failure")
        self.objects.pop((value.path, value.generation), None)
        self.deleted.append(value)


class MemoryTokenStore:
    def __init__(self, token: int = 123) -> None:
        self.token = token
        self.records: dict[int, StateTokenRecord] = {}
        self.fail_claim = False

    def claim(
        self,
        payload: StatePayloadReference,
        *,
        created_at: datetime,
        expires_at: datetime,
    ) -> tuple[int, StatePayloadReference | None]:
        if self.fail_claim:
            raise RuntimeError("injected claim failure")
        existing = self.records.get(self.token)
        replaced = (
            existing.payload
            if existing is not None and existing.expires_at <= created_at
            else None
        )
        if existing is not None and existing.expires_at > created_at:
            raise RuntimeError("token is occupied")
        self.records[self.token] = StateTokenRecord(
            self.token,
            payload,
            created_at,
            expires_at,
        )
        return self.token, replaced

    def get(self, token: int, *, now: datetime) -> StateTokenRecord | None:
        record = self.records.get(token)
        if record is None or record.expires_at <= now:
            return None
        return record


def _state() -> api_pb.SystemState:
    state = api_pb.SystemState(model=api_pb.MODEL_III)
    state.registers.pc = 0x1234
    state.memoryRegions.add(start=100, length=4, data=b"abcd")
    return state


def test_persistent_state_round_trip_and_logical_expiry() -> None:
    now = datetime(2026, 8, 7, 13, 0, tzinfo=UTC)
    clock = [now]
    payloads = MemoryPayloadStore()
    tokens = MemoryTokenStore()
    storage = PersistentStateStorage(payloads, tokens, clock=lambda: clock[0])

    token = storage.save_state(_state())

    assert token == 123
    assert storage.get_state(token) == _state()
    assert tokens.records[token].expires_at == now + timedelta(days=7)

    clock[0] = now + timedelta(days=7)
    assert storage.get_state(token) is None


def test_failed_token_claim_deletes_the_unreferenced_payload() -> None:
    payloads = MemoryPayloadStore()
    tokens = MemoryTokenStore()
    tokens.fail_claim = True
    storage = PersistentStateStorage(payloads, tokens)

    with pytest.raises(RuntimeError, match="claim failure"):
        storage.save_state(_state())

    assert payloads.objects == {}
    assert len(payloads.deleted) == 1


def test_expired_token_replacement_deletes_the_old_generation() -> None:
    now = datetime(2026, 8, 7, 13, 0, tzinfo=UTC)
    payloads = MemoryPayloadStore()
    tokens = MemoryTokenStore()
    storage = PersistentStateStorage(payloads, tokens, clock=lambda: now)
    old = payloads.create(b"old", hashlib.sha256(b"old").hexdigest())
    tokens.records[123] = StateTokenRecord(
        123,
        old,
        now - timedelta(days=8),
        now - timedelta(days=1),
    )

    assert storage.save_state(_state()) == 123

    assert old in payloads.deleted
    assert (old.path, old.generation) not in payloads.objects


def test_download_rejects_tampered_payload_bytes() -> None:
    payloads = MemoryPayloadStore()
    tokens = MemoryTokenStore()
    storage = PersistentStateStorage(payloads, tokens)
    token = storage.save_state(_state())
    reference = tokens.records[token].payload
    payloads.objects[(reference.path, reference.generation)] = b"tampered"

    with pytest.raises(ValueError, match="size does not match"):
        storage.get_state(token)


def test_state_clock_must_be_timezone_aware() -> None:
    storage = PersistentStateStorage(
        MemoryPayloadStore(),
        MemoryTokenStore(),
        clock=lambda: datetime(2026, 8, 7),
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        storage.save_state(_state())

"""Checksum-verifying persistence boundary for public system-state tokens."""

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from google.protobuf.message import DecodeError

from retrostore.generated import ApiProtos_pb2 as api_pb

STATE_TTL = timedelta(days=7)

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StatePayloadReference:
    path: str
    generation: int
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class StateTokenRecord:
    token: int
    payload: StatePayloadReference
    created_at: datetime
    expires_at: datetime


class StatePayloadStore(Protocol):
    def create(self, body: bytes, sha256: str) -> StatePayloadReference: ...

    def read(self, value: StatePayloadReference) -> bytes: ...

    def delete(self, value: StatePayloadReference) -> None: ...


class StateTokenStore(Protocol):
    def claim(
        self,
        payload: StatePayloadReference,
        *,
        created_at: datetime,
        expires_at: datetime,
    ) -> tuple[int, StatePayloadReference | None]: ...

    def get(self, token: int, *, now: datetime) -> StateTokenRecord | None: ...

    def list_live(self, *, now: datetime) -> tuple[StateTokenRecord, ...]: ...


class PersistentStateStorage:
    """Store immutable protobuf payloads separately from expiring token metadata."""

    def __init__(
        self,
        payloads: StatePayloadStore,
        tokens: StateTokenStore,
        *,
        clock: Callable[[], datetime] | None = None,
        ttl: timedelta = STATE_TTL,
    ) -> None:
        if ttl <= timedelta(0):
            raise ValueError("State TTL must be positive")
        self._payloads = payloads
        self._tokens = tokens
        self._clock = clock or (lambda: datetime.now(UTC))
        self._ttl = ttl

    def save_state(self, state: api_pb.SystemState) -> int:
        body = state.SerializeToString(deterministic=True)
        digest = hashlib.sha256(body).hexdigest()
        now = _aware_utc(self._clock())
        payload = self._payloads.create(body, digest)
        try:
            token, replaced = self._tokens.claim(
                payload,
                created_at=now,
                expires_at=now + self._ttl,
            )
        except Exception:
            try:
                self._payloads.delete(payload)
            except Exception:
                _LOG.warning(
                    "State token claim failed and its unreferenced payload could not be deleted",
                    exc_info=True,
                )
            raise

        if replaced is not None:
            try:
                self._payloads.delete(replaced)
            except Exception:
                _LOG.warning(
                    "State token was replaced but its expired payload could not be deleted",
                    exc_info=True,
                )
        return token

    def get_state(self, token: int) -> api_pb.SystemState | None:
        record = self._tokens.get(token, now=_aware_utc(self._clock()))
        if record is None:
            return None
        body = self._payloads.read(record.payload)
        if len(body) != record.payload.size:
            raise ValueError("State payload size does not match its metadata")
        if hashlib.sha256(body).hexdigest() != record.payload.sha256:
            raise ValueError("State payload checksum does not match its metadata")
        try:
            return api_pb.SystemState.FromString(body)
        except DecodeError as error:
            raise ValueError("State payload is not a valid SystemState protobuf") from error


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("State clock values must be timezone-aware")
    return value.astimezone(UTC)

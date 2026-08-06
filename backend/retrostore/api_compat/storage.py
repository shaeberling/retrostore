"""Storage abstraction used by the compatibility API."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from threading import Lock
from typing import Protocol

from google.protobuf.message import Message

from retrostore.generated import ApiProtos_pb2 as api_pb


def _clone[MessageT: Message](message: MessageT) -> MessageT:
    clone = type(message)()
    clone.ParseFromString(message.SerializeToString())
    return clone


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """API-facing catalog projection plus the media-presence filter fields."""

    app: api_pb.App
    media_types: frozenset[int] = frozenset()


@dataclass(frozen=True, slots=True)
class MediaSlot:
    """One legacy TRS-80 media slot, including empty positional slots."""

    media_type: int
    image: api_pb.MediaImage


class CompatibilityStorage(Protocol):
    """Persistence operations required by the frozen public API."""

    def get_catalog_entry(self, app_id: str) -> CatalogEntry | None: ...

    def list_catalog_entries(self) -> Sequence[CatalogEntry]: ...

    def search_app_ids(self, query: str) -> set[str]: ...

    def get_media_slots(self, app_id: str) -> Sequence[MediaSlot]: ...

    def save_state(self, state: api_pb.SystemState) -> int: ...

    def get_state(self, token: int) -> api_pb.SystemState | None: ...


class InMemoryCompatibilityStorage:
    """Deterministic adapter for local compatibility and emulator tests."""

    def __init__(
        self,
        catalog: Iterable[CatalogEntry] = (),
        media: dict[str, Sequence[MediaSlot]] | None = None,
        states: dict[int, api_pb.SystemState] | None = None,
        *,
        first_state_token: int = 100,
    ) -> None:
        self._catalog = {
            entry.app.id: CatalogEntry(_clone(entry.app), frozenset(entry.media_types))
            for entry in catalog
        }
        self._media = {
            app_id: tuple(MediaSlot(slot.media_type, _clone(slot.image)) for slot in slots)
            for app_id, slots in (media or {}).items()
        }
        self._states = {token: _clone(state) for token, state in (states or {}).items()}
        self._next_state_token = first_state_token
        self._state_lock = Lock()

    def get_catalog_entry(self, app_id: str) -> CatalogEntry | None:
        entry = self._catalog.get(app_id)
        if entry is None:
            return None
        return CatalogEntry(_clone(entry.app), entry.media_types)

    def list_catalog_entries(self) -> Sequence[CatalogEntry]:
        return tuple(
            CatalogEntry(_clone(entry.app), entry.media_types)
            for entry in self._catalog.values()
        )

    def search_app_ids(self, query: str) -> set[str]:
        needle = query.casefold()
        return {
            entry.app.id
            for entry in self._catalog.values()
            if needle in entry.app.name.casefold() or needle in entry.app.description.casefold()
        }

    def get_media_slots(self, app_id: str) -> Sequence[MediaSlot]:
        return tuple(
            MediaSlot(slot.media_type, _clone(slot.image))
            for slot in self._media.get(app_id, ())
        )

    def save_state(self, state: api_pb.SystemState) -> int:
        with self._state_lock:
            token = self._next_available_token()
            self._states[token] = _clone(state)
            self._next_state_token = token + 1
            return token

    def get_state(self, token: int) -> api_pb.SystemState | None:
        state = self._states.get(token)
        return None if state is None else _clone(state)

    def _next_available_token(self) -> int:
        token = self._next_state_token
        while token in self._states:
            token += 1
        return token

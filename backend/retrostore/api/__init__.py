"""Public RetroStore API implementation and persistence boundary."""

from retrostore.api.service import RetroStoreApi, build_handlers
from retrostore.api.storage import (
    ApiDataStore,
    CatalogEntry,
    InMemoryApiDataStore,
    MediaSlot,
)

__all__ = [
    "CatalogEntry",
    "RetroStoreApi",
    "ApiDataStore",
    "InMemoryApiDataStore",
    "MediaSlot",
    "build_handlers",
]

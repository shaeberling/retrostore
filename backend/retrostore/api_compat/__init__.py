"""Legacy-compatible API implementation and persistence boundary."""

from retrostore.api_compat.service import CompatibilityApi, build_handlers
from retrostore.api_compat.storage import (
    CatalogEntry,
    CompatibilityStorage,
    InMemoryCompatibilityStorage,
    MediaSlot,
)

__all__ = [
    "CatalogEntry",
    "CompatibilityApi",
    "CompatibilityStorage",
    "InMemoryCompatibilityStorage",
    "MediaSlot",
    "build_handlers",
]

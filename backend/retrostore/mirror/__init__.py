"""Normalized catalog mirror and compatibility persistence adapters."""

from retrostore.mirror.catalog import (
    CatalogMirror,
    MappingObjectReader,
    MirrorCompatibilityStorage,
    NormalizedApp,
    NormalizedMedia,
    NormalizedScreenshot,
    load_catalog_mirror_archive,
    write_catalog_mirror_archive,
)
from retrostore.mirror.persistence import (
    CatalogImportReport,
    CatalogSnapshot,
    CatalogSnapshotStore,
    CatalogStageReport,
    ImmutableObject,
    ImmutableObjectStore,
    build_catalog_snapshot,
    import_catalog_mirror,
    load_active_catalog_mirror,
    stage_catalog_mirror,
)

__all__ = [
    "CatalogMirror",
    "CatalogImportReport",
    "CatalogStageReport",
    "CatalogSnapshot",
    "CatalogSnapshotStore",
    "ImmutableObject",
    "ImmutableObjectStore",
    "MappingObjectReader",
    "MirrorCompatibilityStorage",
    "NormalizedApp",
    "NormalizedMedia",
    "NormalizedScreenshot",
    "build_catalog_snapshot",
    "import_catalog_mirror",
    "stage_catalog_mirror",
    "load_active_catalog_mirror",
    "load_catalog_mirror_archive",
    "write_catalog_mirror_archive",
]

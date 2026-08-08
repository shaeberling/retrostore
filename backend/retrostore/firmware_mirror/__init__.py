"""Normalized legacy firmware mirror and persistence adapters."""

from retrostore.firmware_mirror.model import (
    FirmwareMirror,
    MappingObjectReader,
    NormalizedFirmware,
    load_firmware_mirror_archive,
)
from retrostore.firmware_mirror.persistence import (
    FirmwareImportReport,
    FirmwareSnapshot,
    FirmwareSnapshotStore,
    build_firmware_snapshot,
    import_firmware_mirror,
    load_active_firmware_mirror,
)

__all__ = [
    "FirmwareImportReport",
    "FirmwareMirror",
    "FirmwareSnapshot",
    "FirmwareSnapshotStore",
    "MappingObjectReader",
    "NormalizedFirmware",
    "build_firmware_snapshot",
    "import_firmware_mirror",
    "load_active_firmware_mirror",
    "load_firmware_mirror_archive",
]

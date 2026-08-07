import json
import warnings
import zipfile
from pathlib import Path

import pytest

from retrostore.mirror import load_catalog_mirror_archive
from tests.mirror.test_catalog import _manifest, _reader, _reconciliation


def _write_archive(
    path: Path,
    *,
    manifest: dict[str, object] | None = None,
    objects: dict[str, bytes] | None = None,
    extras: dict[str, bytes] | None = None,
) -> None:
    object_values = dict(_reader().objects) if objects is None else objects
    manifest_value = _manifest() if manifest is None else manifest
    manifest_value["reconciliation"] = _reconciliation(object_values)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest_value))
        for object_path, body in object_values.items():
            archive.writestr(f"objects/{object_path}", body)
        for name, body in (extras or {}).items():
            archive.writestr(name, body)


def test_loads_export_archive_and_verifies_every_object(tmp_path: Path) -> None:
    path = tmp_path / "catalog.zip"
    _write_archive(path)

    mirror = load_catalog_mirror_archive(path)

    assert mirror.source_project_id == "trs-80"
    assert [app.id for app in mirror.apps] == ["app-1"]
    assert len(mirror.object_bytes) == 3


def test_rejects_tampered_and_unreferenced_archive_objects(tmp_path: Path) -> None:
    tampered_path = tmp_path / "tampered.zip"
    objects = dict(_reader().objects)
    objects["media/app-1/media-disk/disk"] = b"disk imagf"
    _write_archive(tampered_path, objects=objects)
    with pytest.raises(ValueError, match="checksum mismatch"):
        load_catalog_mirror_archive(tampered_path)

    extra_path = tmp_path / "extra.zip"
    _write_archive(extra_path, extras={"objects/media/app-1/orphan/content": b"orphan"})
    with pytest.raises(ValueError, match="unreferenced objects"):
        load_catalog_mirror_archive(extra_path)


def test_rejects_duplicate_or_unsafe_archive_entries(tmp_path: Path) -> None:
    duplicate_path = tmp_path / "duplicate.zip"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(duplicate_path, "w") as archive:
            archive.writestr("manifest.json", "{}")
            archive.writestr("manifest.json", "{}")
    with pytest.raises(ValueError, match="duplicate entries"):
        load_catalog_mirror_archive(duplicate_path)

    unsafe_path = tmp_path / "unsafe.zip"
    _write_archive(unsafe_path, extras={"objects/../outside": b"bad"})
    with pytest.raises(ValueError, match="normalized and relative"):
        load_catalog_mirror_archive(unsafe_path)


def test_rejects_unknown_top_level_archive_entry(tmp_path: Path) -> None:
    path = tmp_path / "unknown.zip"
    _write_archive(path, extras={"notes.txt": b"unexpected"})

    with pytest.raises(ValueError, match="Unsupported catalog mirror archive entry"):
        load_catalog_mirror_archive(path)

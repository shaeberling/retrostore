import hashlib
import subprocess
from pathlib import Path

import pytest

from retrostore.contract.consumer_clients import (
    TRS80_CLIENT_FILES,
    TRS80_EMBEDDED_C_METHODS,
    TRS80_KMP_METHODS,
    TRS80_REVISION,
    validate_trs80_client,
    validate_trs80_revision,
)
from retrostore.contracts import PUBLIC_API_METHODS


def test_trs80_consumers_use_only_frozen_public_methods() -> None:
    assert {
        "getApp",
        "listApps",
        "fetchMediaImages",
        "uploadState",
        "downloadState",
    } == TRS80_KMP_METHODS
    assert {
        "getApp",
        "listApps",
        "fetchMediaImages",
    } == TRS80_EMBEDDED_C_METHODS
    assert PUBLIC_API_METHODS.keys() >= TRS80_KMP_METHODS | TRS80_EMBEDDED_C_METHODS


def test_validate_trs80_revision_accepts_reviewed_revision(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    completed = subprocess.CompletedProcess([], 0, stdout=f"{TRS80_REVISION}\n", stderr="")
    monkeypatch.setattr(
        "retrostore.contract.consumer_clients.subprocess.run", lambda *args, **kwargs: completed
    )

    validate_trs80_revision(tmp_path)


def test_validate_trs80_revision_rejects_another_revision(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    completed = subprocess.CompletedProcess([], 0, stdout=f"{'0' * 40}\n", stderr="")
    monkeypatch.setattr(
        "retrostore.contract.consumer_clients.subprocess.run", lambda *args, **kwargs: completed
    )

    with pytest.raises(ValueError, match="must be reviewed revision"):
        validate_trs80_revision(tmp_path)


def test_validate_trs80_client_accepts_reviewed_sources(tmp_path: Path) -> None:
    for name in TRS80_CLIENT_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"reviewed")

    reviewed_digest = hashlib.sha256(b"reviewed").hexdigest()
    expected_files = dict.fromkeys(TRS80_CLIENT_FILES, reviewed_digest)
    validate_trs80_client(tmp_path, expected_files)


def test_validate_trs80_client_rejects_changed_source(tmp_path: Path) -> None:
    for name in TRS80_CLIENT_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"changed")

    with pytest.raises(ValueError, match="does not match reviewed revision"):
        validate_trs80_client(tmp_path)

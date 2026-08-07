import hashlib
from pathlib import Path

import pytest

from retrostore.contract.consumer_clients import TRS80_CLIENT_FILES, validate_trs80_client


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

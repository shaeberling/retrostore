import hashlib
import json
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import retrostore.api_compat.export_state_snapshot as export_command
from retrostore.api_compat.state_archive import load_state_archive
from retrostore.api_compat.state_persistence import StateTokenRecord
from tests.api_compat.test_state_persistence import (
    MemoryPayloadStore,
    MemoryTokenStore,
    _state,
)


def test_exports_live_states_without_putting_tokens_in_the_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime.now(UTC)
    payloads = MemoryPayloadStore()
    tokens = MemoryTokenStore(token=321)
    body = _state().SerializeToString(deterministic=True)
    payload = payloads.create(body, hashlib.sha256(body).hexdigest())
    tokens.records[321] = StateTokenRecord(
        321,
        payload,
        now - timedelta(minutes=1),
        now + timedelta(days=1),
    )
    monkeypatch.setattr(
        export_command,
        "google_state_stores",
        lambda **kwargs: (payloads, tokens),
    )
    archive_path = tmp_path / "states.zip"
    report_path = tmp_path / "report.json"

    assert export_command.main(
        [
            "--project",
            "trs-80",
            "--database",
            "retrostore-state",
            "--bucket",
            "trs-80-retrostore-state",
            "--output-archive",
            str(archive_path),
            "--output-report",
            str(report_path),
            "--impersonate-service-account",
            "retrostore-api@trs-80.iam.gserviceaccount.com",
        ]
    ) == 0

    report = json.loads(report_path.read_text())
    assert report["read_only"] is True
    assert report["evidence"]["state_count"] == 1
    assert report["safety"]["report_contains_state_tokens"] is False
    assert stat.S_IMODE(archive_path.stat().st_mode) == 0o600
    assert [state.token for state in load_state_archive(archive_path).states] == [321]

import hashlib
import stat
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from retrostore.api_compat.state_archive import (
    load_state_archive,
    state_archive_evidence,
    write_state_archive,
)
from retrostore.api_compat.state_persistence import (
    StatePayloadReference,
    StateTokenRecord,
)
from retrostore.generated import ApiProtos_pb2 as api_pb


def _record(
    token: int,
    body: bytes,
    *,
    captured_at: datetime,
    expires_at: datetime | None = None,
) -> tuple[StateTokenRecord, bytes]:
    digest = hashlib.sha256(body).hexdigest()
    reference = StatePayloadReference(
        f"states/cloud-{token}/{digest}.pb",
        token,
        len(body),
        digest,
    )
    return (
        StateTokenRecord(
            token,
            reference,
            captured_at - timedelta(minutes=1),
            expires_at or captured_at + timedelta(days=1),
        ),
        body,
    )


def _body(model: int) -> bytes:
    state = api_pb.SystemState(model=model)
    state.registers.pc = 0x1234
    state.memoryRegions.add(start=0x4000, length=4, data=b"TEST")
    return state.SerializeToString(deterministic=True)


def test_state_archive_is_private_deterministic_and_round_trippable(
    tmp_path: Path,
) -> None:
    captured_at = datetime(2026, 8, 10, 1, 2, 3, 456789, tzinfo=UTC)
    records = (
        _record(321, _body(api_pb.MODEL_I), captured_at=captured_at),
        _record(123, _body(api_pb.MODEL_III), captured_at=captured_at),
    )
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"

    write_state_archive(
        records,
        source_project_id="trs-80",
        captured_at=captured_at,
        path=first,
    )
    write_state_archive(
        records,
        source_project_id="trs-80",
        captured_at=captured_at,
        path=second,
    )
    archive = load_state_archive(first)

    assert first.read_bytes() == second.read_bytes()
    assert stat.S_IMODE(first.stat().st_mode) == 0o600
    assert archive.source_project_id == "trs-80"
    assert [state.token for state in archive.states] == [123, 321]
    assert state_archive_evidence(archive)["state_count"] == 2
    with zipfile.ZipFile(first) as contents:
        assert all(entry.date_time == (1980, 1, 1, 0, 0, 0) for entry in contents.infolist())
    with pytest.raises(FileExistsError):
        write_state_archive(
            records,
            source_project_id="trs-80",
            captured_at=captured_at,
            path=first,
        )


def test_state_archive_rejects_expired_or_tampered_payloads(tmp_path: Path) -> None:
    captured_at = datetime(2026, 8, 10, tzinfo=UTC)
    expired = _record(
        123,
        _body(api_pb.MODEL_I),
        captured_at=captured_at,
        expires_at=captured_at,
    )
    with pytest.raises(ValueError, match="only states live"):
        write_state_archive(
            (expired,),
            source_project_id="trs-80",
            captured_at=captured_at,
            path=tmp_path / "expired.zip",
        )

    record, body = _record(123, _body(api_pb.MODEL_I), captured_at=captured_at)
    tampered = StateTokenRecord(
        record.token,
        record.payload,
        record.created_at,
        record.expires_at,
    )
    with pytest.raises(ValueError, match="checksum"):
        write_state_archive(
            ((tampered, body[:-1] + bytes([body[-1] ^ 0xFF])),),
            source_project_id="trs-80",
            captured_at=captured_at,
            path=tmp_path / "tampered.zip",
        )

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from retrostore.api.state_persistence import (
    StatePayloadReference,
    StateTokenRecord,
)
from retrostore.generated import ApiProtos_pb2 as api_pb
from retrostore.migration.state.plan_legacy_state_reverse_sync import main
from retrostore.migration.state.state_archive import write_state_archive


def test_plan_is_token_free_deterministic_and_has_atomic_route_preconditions(
    tmp_path: Path,
) -> None:
    captured_at = datetime(2026, 8, 10, tzinfo=UTC)
    body = api_pb.SystemState(model=api_pb.MODEL_I).SerializeToString(deterministic=True)
    digest = hashlib.sha256(body).hexdigest()
    record = StateTokenRecord(
        987,
        StatePayloadReference(f"states/private/{digest}.pb", 1, len(body), digest),
        captured_at - timedelta(minutes=1),
        captured_at + timedelta(days=1),
    )
    archive_path = tmp_path / "states.zip"
    output = tmp_path / "plan.json"
    write_state_archive(
        ((record, body),),
        source_project_id="trs-80",
        captured_at=captured_at,
        path=archive_path,
    )

    assert main(["--state-archive", str(archive_path), "--output", str(output)]) == 0

    plan = json.loads(output.read_text())
    assert plan["read_only"] is True
    assert plan["apply_available"] is False
    assert plan["safety"]["contains_state_tokens"] is False
    assert plan["legacy_operations"]["exact_token_state_upsert_count"] == 1
    assert plan["preconditions"]["switch_all_three_state_routes_atomically"] is True
    assert '"token":987' not in output.read_text().replace(" ", "")
    digest = plan.pop("plan_sha256")
    canonical = json.dumps(plan, separators=(",", ":"), sort_keys=True).encode()
    assert digest == hashlib.sha256(canonical).hexdigest()

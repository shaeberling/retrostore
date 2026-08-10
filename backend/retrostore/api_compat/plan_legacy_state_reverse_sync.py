"""Build a token-free read-only plan for replaying live states into App Engine."""

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from retrostore.api_compat.state_archive import (
    StateArchive,
    load_state_archive,
    state_archive_evidence,
)


def build_legacy_state_reverse_plan(
    archive: StateArchive, *, archive_sha256: str
) -> dict[str, Any]:
    """Describe guarded legacy replay without serializing state tokens or payloads."""

    evidence = state_archive_evidence(archive)
    plan: dict[str, Any] = {
        "schema_version": 1,
        "operation": "plan_legacy_state_reverse_sync",
        "read_only": True,
        "apply_available": False,
        "input": {
            "archive_sha256": archive_sha256,
            "source_project_id": archive.source_project_id,
            "captured_at": archive.captured_at.isoformat().replace("+00:00", "Z"),
            "evidence": evidence,
        },
        "safety": {
            "contains_state_tokens": False,
            "contains_state_payloads": False,
            "contains_client_identifiers": False,
            "source_archive_must_remain_mode_0600": True,
        },
        "legacy_operations": {
            "exact_token_state_upsert_count": len(archive.states),
            "state_entity_delete_count": 0,
            "blobstore_operation_count": 0,
            "search_operation_count": 0,
        },
        "legacy_entity_mapping": {
            "token": "SystemState.token",
            "created_at": "SystemState.addTimestamp",
            "model": "SystemState.model",
            "registers": "SystemState.registers",
            "memory_regions": "SystemState.memoryRegions",
            "memory_region_length": "derived_from_data_bytes",
        },
        "preconditions": {
            "freeze_replacement_state_writes": True,
            "keep_legacy_state_writes_disabled_during_replay": True,
            "every_legacy_token_must_be_absent_or_identical": True,
            "never_replace_a_different_live_legacy_state": True,
            "reconcile_all_archive_states_through_legacy_download_RPCS": True,
            "restore_exactly_one_state_writer": True,
            "switch_all_three_state_routes_atomically": True,
        },
        "ordered_apply_phases": [
            "freeze_replacement_state_writes",
            "capture_and_verify_final_mode_0600_state_archive",
            "preflight_every_legacy_token_for_absent_or_identical_content",
            "upsert_exact_tokens_and_original_add_timestamps",
            "verify_full_and_region_downloads_for_every_replayed_state",
            "atomically_route_upload_download_and_region_to_app_engine",
            "restore_exactly_one_legacy_state_writer",
        ],
        "blockers_before_apply_can_exist": [
            "legacy_state_archive_importer_is_not_enabled",
            "legacy_exact_token_collision_preflight_is_not_rehearsed",
            "full_per-state_legacy_RPC_reconciliation_is_not_rehearsed",
        ],
    }
    plan["plan_sha256"] = _json_sha256(plan)
    return plan


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    archive = load_state_archive(args.state_archive)
    plan = build_legacy_state_reverse_plan(
        archive, archive_sha256=_file_sha256(args.state_archive)
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    print(json.dumps(plan, sort_keys=True, separators=(",", ":")))
    return 0


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _json_sha256(value: Any) -> str:
    body = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
    return hashlib.sha256(body).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())

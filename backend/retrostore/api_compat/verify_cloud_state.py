"""Run a guarded real-cloud round trip through isolated public state persistence."""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from retrostore.api_compat.google_cloud_state import (
    google_state_storage,
    state_service_account,
    validate_state_identity,
    validate_state_target,
)
from retrostore.generated import ApiProtos_pb2 as api_pb


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-project")
    parser.add_argument("--impersonate-service-account")
    args = parser.parse_args(argv)

    validate_state_target(
        project=args.project,
        database=args.database,
        bucket=args.bucket,
    )
    report: dict[str, object] = {
        "schema_version": 1,
        "applied": False,
        "target": {
            "project": args.project,
            "database": args.database,
            "bucket": args.bucket,
        },
    }
    if args.apply:
        if args.confirm_project != args.project:
            raise ValueError("--confirm-project must exactly match --project when applying")
        if args.impersonate_service_account is None:
            raise ValueError(
                "--impersonate-service-account is required when applying; expected "
                f"{state_service_account(args.project)}"
            )
        validate_state_identity(args.project, args.impersonate_service_account)
        storage = google_state_storage(
            project=args.project,
            database=args.database,
            bucket=args.bucket,
            impersonate_service_account=args.impersonate_service_account,
        )
        state = _smoke_state()
        token = storage.save_state(state)
        loaded = storage.get_state(token)
        if loaded != state:
            raise ValueError("Cloud state round trip did not preserve the normalized protobuf")
        report.update(
            {
                "applied": True,
                "service_account": args.impersonate_service_account,
                "token_in_legacy_range": 100 <= token <= 999,
                "protobuf_bytes": len(state.SerializeToString(deterministic=True)),
                "round_trip_match": True,
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


def _smoke_state() -> api_pb.SystemState:
    state = api_pb.SystemState(model=api_pb.MODEL_I)
    state.registers.pc = 0x4321
    state.memoryRegions.add(start=0x4000, length=4, data=b"TEST")
    state.memoryRegions.add(start=0x4002, length=2, data=b"OK")
    return state


if __name__ == "__main__":
    raise SystemExit(main())

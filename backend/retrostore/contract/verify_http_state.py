"""Guarded external HTTP lifecycle check for the three public state RPCs."""

import argparse
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from retrostore.contract.exhaustive import (
    _gcloud_identity_token,
    _with_candidate_host_header,
)
from retrostore.generated import ApiProtos_pb2 as api_pb

_PRODUCTION_HOSTS = frozenset({"retrostore.org", "www.retrostore.org"})


def verify_http_state_lifecycle(
    client: httpx.Client,
) -> dict[str, bool | int]:
    """Write and read one synthetic state without returning its allocated token."""

    state = _synthetic_state()
    upload_request = api_pb.UploadSystemStateParams(state=state)
    upload_http = client.post("/api/uploadState", content=upload_request.SerializeToString())
    upload_http.raise_for_status()
    upload = api_pb.ApiResponseUploadSystemState.FromString(upload_http.content)
    if not upload.success:
        raise ValueError(f"Synthetic state upload failed: {upload.message}")
    if not 100 <= upload.token <= 999:
        raise ValueError("Synthetic state upload returned a token outside 100-999")

    download_request = api_pb.DownloadSystemStateParams(token=upload.token)
    download_http = client.post("/api/downloadState", content=download_request.SerializeToString())
    download_http.raise_for_status()
    download = api_pb.ApiResponseDownloadSystemState.FromString(download_http.content)
    if not download.success:
        raise ValueError(f"Synthetic state download failed: {download.message}")
    if download.systemState != state:
        raise ValueError("Synthetic state download did not match the uploaded protobuf")

    excluded_request = api_pb.DownloadSystemStateParams(
        token=upload.token,
        exclude_memory_region_data=True,
    )
    excluded_http = client.post("/api/downloadState", content=excluded_request.SerializeToString())
    excluded_http.raise_for_status()
    excluded = api_pb.ApiResponseDownloadSystemState.FromString(excluded_http.content)
    expected_lengths = [len(region.data) for region in state.memoryRegions]
    if (
        not excluded.success
        or [region.length for region in excluded.systemState.memoryRegions] != expected_lengths
        or any(region.data for region in excluded.systemState.memoryRegions)
    ):
        raise ValueError("Memory-excluded state download did not preserve only lengths")

    region_request = api_pb.DownloadSystemStateMemoryRegionParams(
        token=upload.token,
        start=0x4000,
        length=4,
    )
    region_http = client.post(
        "/api/downloadStateMemoryRegion",
        content=region_request.SerializeToString(),
    )
    region_http.raise_for_status()
    if region_http.content != b"TEOK":
        raise ValueError("Overlapping state regions did not preserve legacy precedence")

    return {
        "upload_success": True,
        "token_in_legacy_range": True,
        "download_round_trip_match": True,
        "exclude_memory_data_match": True,
        "overlap_region_match": True,
        "protobuf_bytes": len(state.SerializeToString(deterministic=True)),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--candidate-gcloud-identity-token-service-account")
    parser.add_argument("--candidate-audience")
    parser.add_argument("--candidate-host-header")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-candidate-url")
    args = parser.parse_args(argv)

    candidate_url = _validate_candidate_url(args.candidate_url)
    if args.candidate_audience and not args.candidate_gcloud_identity_token_service_account:
        raise ValueError("--candidate-audience requires a candidate identity")
    report: dict[str, object] = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "candidate_url": candidate_url,
        "applied": args.apply,
        "safety": {
            "synthetic_state_only": True,
            "contains_state_token": False,
            "production_host_rejected": True,
        },
    }
    if args.apply:
        if args.confirm_candidate_url != candidate_url:
            raise ValueError("--confirm-candidate-url must exactly match --candidate-url")
        headers: Mapping[str, str] | None = None
        if args.candidate_host_header is not None and (
            args.candidate_audience is not None
            or args.candidate_gcloud_identity_token_service_account is not None
        ):
            raise ValueError("The public front-door probe cannot use private authentication")
        if args.candidate_gcloud_identity_token_service_account:
            headers = {
                "Authorization": "Bearer "
                + _gcloud_identity_token(
                    args.candidate_audience or candidate_url,
                    args.candidate_gcloud_identity_token_service_account,
                )
            }
        headers = _with_candidate_host_header(
            candidate_url,
            args.candidate_host_header,
            headers,
        )
        with httpx.Client(
            base_url=candidate_url,
            headers=headers,
            follow_redirects=False,
            timeout=args.timeout_seconds,
        ) as client:
            report["result"] = verify_http_state_lifecycle(client)
        if args.candidate_host_header is not None:
            report["candidate_host_header"] = args.candidate_host_header

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0


def _validate_candidate_url(value: str) -> str:
    candidate_url = value.rstrip("/")
    parsed = urlsplit(candidate_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("--candidate-url must be an absolute HTTP(S) URL")
    if parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError("--candidate-url must contain only scheme, host, and optional port")
    if parsed.hostname.lower() in _PRODUCTION_HOSTS:
        raise ValueError("Refusing to write a synthetic state to the production host")
    return candidate_url


def _synthetic_state() -> api_pb.SystemState:
    state = api_pb.SystemState(model=api_pb.MODEL_I)
    state.registers.pc = 0x4321
    state.memoryRegions.add(start=0x4000, length=4, data=b"TEST")
    state.memoryRegions.add(start=0x4002, length=2, data=b"OK")
    return state


if __name__ == "__main__":
    raise SystemExit(main())

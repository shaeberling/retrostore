"""Discover and compare every public catalog and media record without mutations."""

import argparse
import json
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import httpx

from retrostore.contract.approvals import evaluate_approvals, load_approvals
from retrostore.contract.capture import capture_scenarios
from retrostore.contract.compare_hosts import compare_captures
from retrostore.contract.scenarios import ContractScenario, ScenarioCategory
from retrostore.contracts import PUBLIC_API_METHODS
from retrostore.generated import ApiProtos_pb2 as api_pb

CATALOG_PAGE_SIZE = 100
MAX_REGION_LENGTH = 10 << 18


@dataclass(frozen=True, slots=True)
class ExhaustiveCorpus:
    scenarios: tuple[ContractScenario, ...]
    app_count: int
    media_object_count: int
    media_bytes: int
    media_region_count: int

    def scope(self) -> dict[str, int]:
        return {
            "scenario_count": len(self.scenarios),
            "app_count": self.app_count,
            "media_object_count": self.media_object_count,
            "media_bytes": self.media_bytes,
            "media_region_count": self.media_region_count,
        }


def discover_exhaustive_corpus(client: httpx.Client) -> ExhaustiveCorpus:
    """Build a stable, read-only corpus from the authoritative host's public data."""

    scenarios: list[ContractScenario] = []
    apps: list[api_pb.App] = []
    page = 0
    start = 0
    while True:
        params = api_pb.ListAppsParams(start=start, num=CATALOG_PAGE_SIZE)
        response = _post_protobuf(client, "listApps", params, api_pb.ApiResponseApps)
        if not response.success:
            if apps and response.message == "Parameter 'start' out of range":
                break
            raise ValueError(f"listApps discovery failed at {start}: {response.message}")
        if not response.app:
            break

        scenarios.extend(
            (
                _scenario(f"catalog_page_{page:04d}", "listApps", params),
                _scenario(f"catalog_nano_page_{page:04d}", "listAppsNano", params),
            )
        )
        apps.extend(response.app)
        if len(response.app) < CATALOG_PAGE_SIZE:
            break
        start += len(response.app)
        page += 1

    if not apps:
        raise ValueError("listApps discovery returned an empty catalog")
    app_ids = [app.id for app in apps]
    if any(not app_id for app_id in app_ids) or len(set(app_ids)) != len(app_ids):
        raise ValueError("listApps discovery returned missing or duplicate app IDs")

    media_object_count = 0
    media_bytes = 0
    media_region_count = 0
    for app_index, app in enumerate(apps):
        prefix = f"app_{app_index:04d}"
        scenarios.extend(
            (
                _scenario(
                    f"{prefix}_get",
                    "getApp",
                    api_pb.GetAppParams(app_id=app.id),
                ),
                _scenario(
                    f"{prefix}_media",
                    "fetchMediaImages",
                    api_pb.FetchMediaImagesParams(app_id=app.id),
                ),
            )
        )

        refs_params = api_pb.FetchMediaImageRefsParams(app_id=app.id)
        refs = _post_protobuf(
            client,
            "fetchMediaImageRefs",
            refs_params,
            api_pb.ApiResponseMediaImageRefs,
        )
        if not refs.success:
            raise ValueError(f"fetchMediaImageRefs discovery failed for app {app_index}")
        scenarios.append(_scenario(f"{prefix}_media_refs", "fetchMediaImageRefs", refs_params))

        for media_index, ref in enumerate(refs.mediaImageRef):
            if not ref.token or ref.size <= 0:
                raise ValueError(
                    f"Invalid media reference for app {app_index}, object {media_index}"
                )
            media_object_count += 1
            media_bytes += ref.size
            for chunk_index, offset in enumerate(range(0, ref.size, MAX_REGION_LENGTH)):
                length = min(MAX_REGION_LENGTH, ref.size - offset)
                scenarios.append(
                    _scenario(
                        f"{prefix}_media_{media_index:02d}_region_{chunk_index:04d}",
                        "fetchMediaImageRegion",
                        api_pb.FetchMediaImageRegionParams(
                            token=ref.token,
                            start=offset,
                            length=length,
                        ),
                    )
                )
                media_region_count += 1

    if any(scenario.method.name == "uploadState" for scenario in scenarios):
        raise AssertionError("Exhaustive catalog/media corpus must remain read-only")
    return ExhaustiveCorpus(
        scenarios=tuple(scenarios),
        app_count=len(apps),
        media_object_count=media_object_count,
        media_bytes=media_bytes,
        media_region_count=media_region_count,
    )


def compare_exhaustive(
    reference_url: str,
    candidate_url: str,
    timeout_seconds: float = 30.0,
    candidate_headers: Mapping[str, str] | None = None,
) -> dict[str, object]:
    with httpx.Client(
        base_url=reference_url,
        follow_redirects=False,
        timeout=timeout_seconds,
    ) as client:
        corpus = discover_exhaustive_corpus(client)

    report = compare_captures(
        capture_scenarios(reference_url, corpus.scenarios, timeout_seconds),
        capture_scenarios(
            candidate_url,
            corpus.scenarios,
            timeout_seconds,
            headers=candidate_headers,
        ),
    )
    report["scope"] = corpus.scope()
    return report


def _scenario(name: str, method: str, request: object) -> ContractScenario:
    if not hasattr(request, "SerializeToString"):
        raise TypeError("Exhaustive requests must be protobuf messages")
    return ContractScenario(
        name=name,
        method=PUBLIC_API_METHODS[method],
        body=request.SerializeToString(),
        category=ScenarioCategory.SUCCESS,
    )


def _post_protobuf(
    client: httpx.Client,
    method: str,
    request: object,
    response_type: type,
):
    if not hasattr(request, "SerializeToString"):
        raise TypeError("Discovery requests must be protobuf messages")
    response = client.post(f"/api/{method}", content=request.SerializeToString())
    if response.status_code != 200:
        raise ValueError(f"{method} discovery returned HTTP {response.status_code}")
    return response_type.FromString(response.content)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-url", required=True)
    parser.add_argument("--candidate-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--approvals", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--candidate-gcloud-identity-token-service-account")
    args = parser.parse_args()

    candidate_headers = None
    if args.candidate_gcloud_identity_token_service_account:
        candidate_headers = {
            "Authorization": "Bearer "
            + _gcloud_identity_token(
                args.candidate_url,
                args.candidate_gcloud_identity_token_service_account,
            )
        }

    report = evaluate_approvals(
        compare_exhaustive(
            args.reference_url,
            args.candidate_url,
            args.timeout_seconds,
            candidate_headers,
        ),
        load_approvals(args.approvals) if args.approvals else (),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if not report["approval_gate"]["passes"]:
        raise SystemExit(1)


def _gcloud_identity_token(audience: str, service_account: str) -> str:
    try:
        completed = subprocess.run(
            [
                "gcloud",
                "auth",
                "print-identity-token",
                f"--impersonate-service-account={service_account}",
                f"--audiences={audience.rstrip('/')}",
                "--include-email",
                "--quiet",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or "gcloud exited unsuccessfully"
        raise RuntimeError(f"Could not impersonate {service_account}: {detail}") from None
    token = completed.stdout.strip()
    if not token:
        raise RuntimeError("gcloud returned an empty identity token")
    return token


if __name__ == "__main__":
    main()

"""Binary-safe, read-only comparison corpus for public firmware routes."""

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import httpx


@dataclass(frozen=True, slots=True)
class FirmwareScenario:
    name: str
    method: str
    path: str


@dataclass(frozen=True, slots=True)
class FirmwareObservation:
    scenario: str
    status: int
    content_type: str
    cors: str | None
    body_size: int
    body_sha256: str
    text_body: str | None


def firmware_scenarios() -> tuple[FirmwareScenario, ...]:
    return (
        FirmwareScenario("card_latest_version", "GET", "/card/1/version"),
        FirmwareScenario("trs_io_latest_version", "GET", "/trs-io/1/version"),
        FirmwareScenario("card_missing_revision_version", "GET", "/card/0/version"),
        FirmwareScenario("trs_io_missing_revision_version", "GET", "/trs-io/0/version"),
        FirmwareScenario("card_latest_firmware", "GET", "/card/1/firmware"),
        FirmwareScenario("trs_io_latest_firmware", "GET", "/trs-io/1/firmware"),
        FirmwareScenario("card_missing_firmware", "GET", "/card/0/firmware"),
        FirmwareScenario("trs_io_missing_firmware", "GET", "/trs-io/0/firmware"),
        FirmwareScenario("card_invalid_revision", "GET", "/card/not-a-number/version"),
        FirmwareScenario("card_revision_overflow", "GET", "/card/2147483648/version"),
        FirmwareScenario("card_unknown_operation", "GET", "/card/1/unknown"),
        FirmwareScenario("card_invalid_url", "GET", "/card/1/firmware/extra"),
        FirmwareScenario("card_signed_revision", "GET", "/card/+1/version"),
        FirmwareScenario("card_negative_revision", "GET", "/card/-1/version"),
        FirmwareScenario("card_trailing_slash", "GET", "/card/1/version/"),
        FirmwareScenario("card_post_version", "POST", "/card/1/version"),
    )


def capture_firmware(
    base_url: str,
    timeout_seconds: float = 30.0,
    *,
    headers: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    with httpx.Client(
        base_url=base_url,
        timeout=timeout_seconds,
        follow_redirects=False,
        headers=headers,
    ) as client:
        return capture_firmware_with_client(base_url, client)


def capture_firmware_with_client(
    base_url: str,
    client: httpx.Client,
    scenarios: Sequence[FirmwareScenario] | None = None,
) -> dict[str, Any]:
    selected = tuple(scenarios or firmware_scenarios())
    observations = []
    for scenario in selected:
        response = client.request(scenario.method, scenario.path)
        content_type = response.headers.get("content-type", "")
        is_binary = content_type.split(";", 1)[0].strip() == "application/octet-stream"
        observation = FirmwareObservation(
            scenario=scenario.name,
            status=response.status_code,
            content_type=content_type,
            cors=response.headers.get("access-control-allow-origin"),
            body_size=len(response.content),
            body_sha256=hashlib.sha256(response.content).hexdigest(),
            text_body=None if is_binary else response.content.decode("iso-8859-1"),
        )
        observations.append(asdict(observation))
    return {
        "schema_version": 1,
        "captured_at": datetime.now(UTC).isoformat(),
        "base_url": base_url.rstrip("/"),
        "scenario_count": len(selected),
        "observations": observations,
    }


def compare_firmware_captures(
    reference: Mapping[str, Any], candidate: Mapping[str, Any]
) -> dict[str, Any]:
    reference_by_name = {
        item["scenario"]: item for item in reference["observations"]
    }
    candidate_by_name = {
        item["scenario"]: item for item in candidate["observations"]
    }
    results = []
    for name in sorted(set(reference_by_name) | set(candidate_by_name)):
        expected = reference_by_name.get(name)
        actual = candidate_by_name.get(name)
        differences = {}
        if expected is None or actual is None:
            differences["scenario_presence"] = {
                "reference": expected is not None,
                "candidate": actual is not None,
            }
        else:
            for field in (
                "status",
                "content_type",
                "cors",
                "body_size",
                "body_sha256",
                "text_body",
            ):
                if expected[field] != actual[field]:
                    differences[field] = {
                        "reference": expected[field],
                        "candidate": actual[field],
                    }
        results.append({"scenario": name, "differences": differences})
    different = sum(bool(result["differences"]) for result in results)
    return {
        "schema_version": 1,
        "reference_url": reference["base_url"],
        "candidate_url": candidate["base_url"],
        "summary": {
            "total": len(results),
            "matching": len(results) - different,
            "different": different,
        },
        "results": results,
    }

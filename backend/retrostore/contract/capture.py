"""Capture mutation-safe compatibility observations from a configured host."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from retrostore.contract.observations import observe_response
from retrostore.contract.scenarios import all_safe_scenarios


def capture(base_url: str, timeout_seconds: float = 30.0) -> dict[str, Any]:
    scenarios = all_safe_scenarios()
    observations = []
    with httpx.Client(base_url=base_url, follow_redirects=False, timeout=timeout_seconds) as client:
        for scenario in scenarios:
            # Existing browser and embedded clients intentionally omit Content-Type.
            response = client.post(f"/api/{scenario.method.name}", content=scenario.body)
            observations.append(observe_response(scenario, response).to_dict())

    return {
        "schema_version": 2,
        "captured_at": datetime.now(UTC).isoformat(),
        "base_url": base_url.rstrip("/"),
        "scenario_count": len(scenarios),
        "observations": observations,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args()

    result = capture(args.base_url, args.timeout_seconds)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()

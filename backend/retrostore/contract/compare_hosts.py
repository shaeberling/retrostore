"""Run the mutation-safe corpus against two hosts and report differences."""

import argparse
import json
from pathlib import Path
from typing import Any

from retrostore.contract.capture import capture
from retrostore.contract.observations import ResponseObservation, compare_observations


def compare_captures(reference: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    reference_by_scenario = {
        value["scenario"]: ResponseObservation.from_dict(value)
        for value in reference["observations"]
    }
    candidate_by_scenario = {
        value["scenario"]: ResponseObservation.from_dict(value)
        for value in candidate["observations"]
    }

    scenario_names = sorted(set(reference_by_scenario) | set(candidate_by_scenario))
    results = []
    for scenario_name in scenario_names:
        expected = reference_by_scenario.get(scenario_name)
        actual = candidate_by_scenario.get(scenario_name)
        if expected is None or actual is None:
            differences: dict[str, Any] = {
                "scenario_presence": {
                    "reference": expected is not None,
                    "candidate": actual is not None,
                }
            }
        else:
            differences = compare_observations(expected, actual)
        results.append({"scenario": scenario_name, "differences": differences})

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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-url", required=True)
    parser.add_argument("--candidate-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args()

    report = compare_captures(
        capture(args.reference_url, args.timeout_seconds),
        capture(args.candidate_url, args.timeout_seconds),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    if report["summary"]["different"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

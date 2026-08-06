import json
from pathlib import Path

import httpx

from retrostore.contract.compare_hosts import compare_captures
from retrostore.contract.observations import observe_response
from retrostore.contract.scenarios import all_safe_scenarios
from services.api_compat.app import create_representative_app

GOLDEN = Path(__file__).parents[1] / "contract" / "golden" / "live-safe-baseline.json"


def test_representative_candidate_matches_all_reviewed_app_engine_observations() -> None:
    app = create_representative_app({"TESTING": True})
    transport = httpx.WSGITransport(app=app)
    observations = []
    with httpx.Client(transport=transport, base_url="http://local.test") as client:
        for scenario in all_safe_scenarios():
            response = client.post(f"/api/{scenario.method.name}", content=scenario.body)
            observations.append(observe_response(scenario, response).to_dict())

    candidate = {
        "base_url": "http://local.test",
        "observations": observations,
    }
    report = compare_captures(json.loads(GOLDEN.read_text()), candidate)

    assert report["summary"] == {"total": 45, "matching": 45, "different": 0}, report

import base64
import hashlib
import json
from pathlib import Path

from retrostore.contract.observations import normalize_protobuf
from retrostore.contract.scenarios import safe_baseline_scenarios, safe_legacy_json_scenarios
from retrostore.contracts import ResponseKind

GOLDEN = Path(__file__).parent / "golden" / "live-safe-baseline.json"


def test_reviewed_live_baseline_covers_every_safe_scenario() -> None:
    data = json.loads(GOLDEN.read_text())
    expected = {
        scenario.name
        for scenario in (*safe_baseline_scenarios(), *safe_legacy_json_scenarios())
    }

    assert data["schema_version"] == 1
    assert data["base_url"] == "https://retrostore.org"
    assert {observation["scenario"] for observation in data["observations"]} == expected
    assert all(observation["status_code"] == 200 for observation in data["observations"])
    assert all(
        observation["access_control_allow_origin"] == "*"
        for observation in data["observations"]
    )


def test_reviewed_live_baseline_bodies_match_hashes_and_semantics() -> None:
    data = json.loads(GOLDEN.read_text())
    scenarios = {
        scenario.name: scenario
        for scenario in (*safe_baseline_scenarios(), *safe_legacy_json_scenarios())
    }

    for observation in data["observations"]:
        body = base64.b64decode(observation["body_base64"])
        assert len(body) == observation["body_length"]
        assert hashlib.sha256(body).hexdigest() == observation["body_sha256"]

        scenario = scenarios[observation["scenario"]]
        if scenario.method.response_kind == ResponseKind.PROTOBUF:
            assert scenario.method.response_type is not None
            assert (
                normalize_protobuf(scenario.method.response_type, body)
                == observation["semantic_body"]
            )
        else:
            assert observation["semantic_body"] is None

import json
from datetime import UTC, datetime

import pytest

from retrostore.contract.scheduled_compare import (
    ScheduledComparisonConfig,
    run_scheduled_comparison,
)


class MemoryArtifactStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def create(self, object_name: str, body: bytes) -> str:
        assert object_name not in self.objects
        self.objects[object_name] = body
        return f"gs://trs-80-retrostore-assets/{object_name}"


def _config() -> ScheduledComparisonConfig:
    return ScheduledComparisonConfig(
        project="trs-80",
        reference_url="https://retrostore.org",
        candidate_url="https://candidate.example",
        report_bucket="trs-80-retrostore-assets",
    )


def test_scheduled_comparison_uses_identity_token_and_retains_report(capsys) -> None:
    store = MemoryArtifactStore()
    calls: list[tuple[object, ...]] = []

    def comparator(*args: object) -> dict[str, object]:
        calls.append(args)
        return {
            "schema_version": 1,
            "reference_url": args[0],
            "candidate_url": args[1],
            "summary": {"total": 158, "matching": 158, "different": 0},
            "scope": {"scenario_count": 158},
            "results": [],
        }

    def surface_comparator(*args: object) -> dict[str, object]:
        calls.append(("surfaces", *args))
        return {
            "legacy_downloads": {
                "summary": {"total": 94, "matching": 94, "different": 0, "passes": True},
                "scope": {"scenario_count": 94},
                "differences": [],
            },
            "public_app_list": {
                "summary": {"different": 0, "passes": True},
                "scope": {"reference_app_count": 32, "candidate_app_count": 32},
                "differences": [],
            },
        }

    result = run_scheduled_comparison(
        _config(),
        store,
        now=datetime(2026, 8, 10, 3, 4, 5, tzinfo=UTC),
        token_fetcher=lambda audience: f"secret-token-for-{audience}",
        comparator=comparator,
        surface_comparator=surface_comparator,
    )

    assert calls[0] == (
        "https://retrostore.org",
        "https://candidate.example",
        30.0,
        {"Authorization": "Bearer secret-token-for-https://candidate.example"},
    )
    assert calls[1][0] == "surfaces"
    assert calls[1][1] == _config()
    assert calls[1][2] == {
        "Authorization": "Bearer secret-token-for-https://candidate.example"
    }
    assert calls[1][3] == datetime(2026, 8, 10, 3, 4, 5, tzinfo=UTC)
    assert result["summary"] == {"total": 158, "matching": 158, "different": 0}
    assert result["approval_gate"]["passes"] is True
    assert len(store.objects) == 1
    object_name, body = next(iter(store.objects.items()))
    assert object_name.startswith("operations/comparisons/2026/08/10/20260810T030405")
    artifact = json.loads(body)
    assert artifact["schema_version"] == 2
    assert artifact["overall_gate"]["passes"] is True
    assert artifact["surface_reports"]["legacy_downloads"]["summary"]["passes"] is True
    assert "secret-token" not in body.decode()
    log_event = json.loads(capsys.readouterr().out)
    assert log_event["event"] == "scheduled_comparison"
    assert log_event["artifact_uri"].endswith(object_name)
    assert "secret-token" not in json.dumps(log_event)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("project", "wrong-project"),
        ("reference_url", "http://retrostore.org"),
        ("candidate_url", "https://candidate.example/path"),
        ("report_bucket", "unapproved-bucket"),
        ("report_prefix", "catalog/"),
        ("timeout_seconds", 301),
    ),
)
def test_scheduled_comparison_rejects_unsafe_configuration(field: str, value: object) -> None:
    values = {
        "project": "trs-80",
        "reference_url": "https://retrostore.org",
        "candidate_url": "https://candidate.example",
        "report_bucket": "trs-80-retrostore-assets",
        "report_prefix": "operations/comparisons/",
        "timeout_seconds": 30.0,
    }
    values[field] = value

    with pytest.raises(ValueError):
        ScheduledComparisonConfig(**values).validate()  # type: ignore[arg-type]

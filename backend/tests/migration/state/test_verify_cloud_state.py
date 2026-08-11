import json
from pathlib import Path

import pytest

import retrostore.migration.state.verify_cloud_state as state_command
from retrostore.api.storage import InMemoryApiDataStore


def _arguments(output: Path) -> list[str]:
    return [
        "--project",
        "trs-80",
        "--database",
        "retrostore-state",
        "--bucket",
        "trs-80-retrostore-state",
        "--output",
        str(output),
    ]


def test_state_smoke_defaults_to_a_zero_write_dry_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "report.json"

    def unexpected_cloud_clients(**kwargs: str) -> None:
        raise AssertionError(f"dry run constructed cloud clients: {kwargs}")

    monkeypatch.setattr(state_command, "google_state_storage", unexpected_cloud_clients)

    assert state_command.main(_arguments(output)) == 0
    assert json.loads(output.read_text()) == {
        "schema_version": 1,
        "applied": False,
        "target": {
            "project": "trs-80",
            "database": "retrostore-state",
            "bucket": "trs-80-retrostore-state",
        },
    }


def test_state_smoke_apply_requires_exact_identity_and_round_trips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "report.json"
    storage = InMemoryApiDataStore()
    monkeypatch.setattr(
        state_command,
        "google_state_storage",
        lambda **kwargs: storage,
    )

    assert (
        state_command.main(
            [
                *_arguments(output),
                "--apply",
                "--confirm-project",
                "trs-80",
                "--impersonate-service-account",
                "retrostore-api@trs-80.iam.gserviceaccount.com",
            ]
        )
        == 0
    )

    report = json.loads(output.read_text())
    assert report["applied"] is True
    assert report["token_in_legacy_range"] is True
    assert report["round_trip_match"] is True
    assert report["service_account"] == "retrostore-api@trs-80.iam.gserviceaccount.com"


def test_state_smoke_rejects_other_apply_identities(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="project API runtime identity"):
        state_command.main(
            [
                *_arguments(tmp_path / "report.json"),
                "--apply",
                "--confirm-project",
                "trs-80",
                "--impersonate-service-account",
                "retrostore-admin@trs-80.iam.gserviceaccount.com",
            ]
        )

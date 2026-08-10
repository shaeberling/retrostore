import json
from pathlib import Path

import httpx
import pytest

import retrostore.contract.verify_http_state as command
from services.api_compat.app import create_representative_app


def test_http_state_lifecycle_checks_all_three_state_rpcs_without_returning_token() -> None:
    app = create_representative_app()
    transport = httpx.WSGITransport(app=app)

    with httpx.Client(transport=transport, base_url="http://candidate.test") as client:
        result = command.verify_http_state_lifecycle(client)

    assert result == {
        "upload_success": True,
        "token_in_legacy_range": True,
        "download_round_trip_match": True,
        "exclude_memory_data_match": True,
        "overlap_region_match": True,
        "protobuf_bytes": 34,
    }
    assert not any(key == "token" for key in result)


def test_command_defaults_to_no_network_dry_run(tmp_path: Path, monkeypatch) -> None:
    output = tmp_path / "state-http.json"
    monkeypatch.setattr(command.httpx, "Client", pytest.fail)

    assert (
        command.main(
            [
                "--candidate-url",
                "https://candidate.example",
                "--output",
                str(output),
            ]
        )
        == 0
    )

    report = json.loads(output.read_text())
    assert report["applied"] is False
    assert "result" not in report
    assert report["safety"]["contains_state_token"] is False


def test_apply_requires_exact_confirmation_and_rejects_production(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="exactly match"):
        command.main(
            [
                "--candidate-url",
                "https://candidate.example",
                "--output",
                str(tmp_path / "wrong.json"),
                "--apply",
                "--confirm-candidate-url",
                "https://other.example",
            ]
        )

    with pytest.raises(ValueError, match="production host"):
        command.main(
            [
                "--candidate-url",
                "https://retrostore.org",
                "--output",
                str(tmp_path / "production.json"),
                "--apply",
                "--confirm-candidate-url",
                "https://retrostore.org",
            ]
        )


def test_apply_mints_identity_token_and_writes_aggregate_report(
    tmp_path: Path, monkeypatch
) -> None:
    output = tmp_path / "applied.json"
    observed: dict[str, object] = {}

    def identity_token(url, account):
        observed["audience"] = url
        observed["identity"] = account
        return "secret"

    monkeypatch.setattr(command, "_gcloud_identity_token", identity_token)

    class Client:
        def __init__(self, **kwargs) -> None:
            observed.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

    monkeypatch.setattr(command.httpx, "Client", Client)
    monkeypatch.setattr(
        command,
        "verify_http_state_lifecycle",
        lambda _client: {"upload_success": True, "token_in_legacy_range": True},
    )

    assert (
        command.main(
            [
                "--candidate-url",
                "https://candidate.example/",
                "--output",
                str(output),
                "--candidate-gcloud-identity-token-service-account",
                "api@example.iam.gserviceaccount.com",
                "--candidate-audience",
                "https://service.example",
                "--apply",
                "--confirm-candidate-url",
                "https://candidate.example",
            ]
        )
        == 0
    )

    assert observed["base_url"] == "https://candidate.example"
    assert observed["audience"] == "https://service.example"
    assert observed["headers"] == {"Authorization": "Bearer secret"}
    report = json.loads(output.read_text())
    assert report["result"]["token_in_legacy_range"] is True
    assert "secret" not in output.read_text()


def test_pre_dns_apply_uses_only_the_approved_host_override(
    tmp_path: Path, monkeypatch
) -> None:
    output = tmp_path / "pre-dns.json"
    observed: dict[str, object] = {}

    class Client:
        def __init__(self, **kwargs) -> None:
            observed.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

    monkeypatch.setattr(command.httpx, "Client", Client)
    monkeypatch.setattr(
        command,
        "verify_http_state_lifecycle",
        lambda _client: {"upload_success": True},
    )

    assert (
        command.main(
            [
                "--candidate-url",
                "http://34.102.211.182",
                "--candidate-host-header",
                "next.retrostore.org",
                "--output",
                str(output),
                "--apply",
                "--confirm-candidate-url",
                "http://34.102.211.182",
            ]
        )
        == 0
    )

    assert observed["headers"] == {"Host": "next.retrostore.org"}
    assert json.loads(output.read_text())["candidate_host_header"] == (
        "next.retrostore.org"
    )

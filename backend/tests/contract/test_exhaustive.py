import httpx
import pytest

from retrostore.contract.capture import capture_scenarios_with_client
from retrostore.contract.exhaustive import (
    _gcloud_identity_token,
    _public_candidate_origin,
    _with_candidate_host_header,
    discover_exhaustive_corpus,
)
from services.api_compat.app import create_representative_app


def test_exhaustive_corpus_covers_every_fixture_app_and_media_object() -> None:
    app = create_representative_app()
    transport = httpx.WSGITransport(app=app)
    with httpx.Client(
        transport=transport,
        base_url="http://candidate.test",
    ) as client:
        corpus = discover_exhaustive_corpus(client)

    assert corpus.scope() == {
        "scenario_count": 100,
        "app_count": 32,
        "media_object_count": 2,
        "media_bytes": 101_781,
        "media_region_count": 2,
    }
    assert {scenario.method.name for scenario in corpus.scenarios} == {
        "getApp",
        "listApps",
        "listAppsNano",
        "fetchMediaImages",
        "fetchMediaImageRefs",
        "fetchMediaImageRegion",
    }


def test_exhaustive_corpus_replays_with_semantic_binary_summaries() -> None:
    app = create_representative_app()
    transport = httpx.WSGITransport(app=app)
    with httpx.Client(
        transport=transport,
        base_url="http://candidate.test",
    ) as client:
        corpus = discover_exhaustive_corpus(client)

        capture = capture_scenarios_with_client(
            "http://candidate.test",
            corpus.scenarios,
            client,
        )

    assert capture["scenario_count"] == 100
    command_media = next(
        observation
        for observation in capture["observations"]
        if observation["scenario"] == "app_0030_media"
    )
    assert command_media["semantic_body"]["mediaImage"][5]["data"] == {
        "size": 3_477,
        "sha256": "312f570af4c76ed5f3ba50a0e68ba02a9188ebc0f49f459f6ffd751812d1f6d3",
    }


def test_gcloud_identity_token_is_captured_without_logging_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def completed(command: list[str], **kwargs: object) -> object:
        calls.append(command)
        return type("Result", (), {"stdout": "secret-token\n"})()

    monkeypatch.setattr("retrostore.contract.exhaustive.subprocess.run", completed)

    assert (
        _gcloud_identity_token(
            "https://candidate.example/",
            "candidate@example.iam.gserviceaccount.com",
        )
        == "secret-token"
    )
    assert calls == [
        [
            "gcloud",
            "auth",
            "print-identity-token",
            "--impersonate-service-account=candidate@example.iam.gserviceaccount.com",
            "--audiences=https://candidate.example",
            "--include-email",
            "--quiet",
        ]
    ]


def test_pre_dns_host_override_is_limited_to_approved_global_http_front_door() -> None:
    assert _with_candidate_host_header(
        "http://34.102.211.182",
        "next.retrostore.org",
        {"Example": "value"},
    ) == {"Example": "value", "Host": "next.retrostore.org"}

    with pytest.raises(ValueError, match="approved HTTP front door"):
        _with_candidate_host_header(
            "https://34.102.211.182",
            "next.retrostore.org",
        )
    with pytest.raises(ValueError, match="numeric load-balancer"):
        _with_candidate_host_header(
            "http://candidate.example",
            "next.retrostore.org",
        )
    with pytest.raises(ValueError, match="approved HTTP front door"):
        _with_candidate_host_header(
            "http://user:password@34.102.211.182",
            "next.retrostore.org",
        )


def test_public_candidate_origin_is_limited_to_reviewed_worker_hosts() -> None:
    preview = "https://retrostore-front-door-preview.retrostore-cloudflare-worker.workers.dev"
    assert _public_candidate_origin(preview + "/") == preview
    assert _public_candidate_origin("https://next.retrostore.org") == (
        "https://next.retrostore.org"
    )
    assert _public_candidate_origin("http://next.retrostore.org") == ("http://next.retrostore.org")

    for invalid in (
        "http://retrostore-front-door-preview.retrostore-cloudflare-worker.workers.dev",
        "https://retrostore.org",
        "https://next.retrostore.org/path",
        "https://next.retrostore.org:443",
        "https://user:password@next.retrostore.org",
    ):
        with pytest.raises(ValueError, match="approved Worker origin"):
            _public_candidate_origin(invalid)

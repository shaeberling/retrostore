import hashlib
import subprocess
from pathlib import Path

import httpx
import pytest

from retrostore.contract.consumer_clients import (
    TRS80_CLIENT_FILES,
    TRS80_EMBEDDED_C_METHODS,
    TRS80_KMP_METHODS,
    TRS80_REVISION,
    create_front_door_proxy_app,
    validate_loopback_candidate_url,
    validate_trs80_client,
    validate_trs80_revision,
)
from retrostore.contracts import PUBLIC_API_METHODS


def test_trs80_consumers_use_only_frozen_public_methods() -> None:
    assert {
        "getApp",
        "listApps",
        "fetchMediaImages",
        "uploadState",
        "downloadState",
    } == TRS80_KMP_METHODS
    assert {
        "getApp",
        "listApps",
        "fetchMediaImages",
    } == TRS80_EMBEDDED_C_METHODS
    assert PUBLIC_API_METHODS.keys() >= TRS80_KMP_METHODS | TRS80_EMBEDDED_C_METHODS


def test_validate_trs80_revision_accepts_reviewed_revision(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    completed = subprocess.CompletedProcess([], 0, stdout=f"{TRS80_REVISION}\n", stderr="")
    monkeypatch.setattr(
        "retrostore.contract.consumer_clients.subprocess.run", lambda *args, **kwargs: completed
    )

    validate_trs80_revision(tmp_path)


def test_validate_trs80_revision_rejects_another_revision(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    completed = subprocess.CompletedProcess([], 0, stdout=f"{'0' * 40}\n", stderr="")
    monkeypatch.setattr(
        "retrostore.contract.consumer_clients.subprocess.run", lambda *args, **kwargs: completed
    )

    with pytest.raises(ValueError, match="must be reviewed revision"):
        validate_trs80_revision(tmp_path)


def test_validate_trs80_client_accepts_reviewed_sources(tmp_path: Path) -> None:
    for name in TRS80_CLIENT_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"reviewed")

    reviewed_digest = hashlib.sha256(b"reviewed").hexdigest()
    expected_files = dict.fromkeys(TRS80_CLIENT_FILES, reviewed_digest)
    validate_trs80_client(tmp_path, expected_files)


def test_validate_trs80_client_rejects_changed_source(tmp_path: Path) -> None:
    for name in TRS80_CLIENT_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"changed")

    with pytest.raises(ValueError, match="does not match reviewed revision"):
        validate_trs80_client(tmp_path)


def test_external_client_gate_accepts_only_an_exact_loopback_origin() -> None:
    assert validate_loopback_candidate_url("http://127.0.0.1:18082/") == (
        "http://127.0.0.1:18082"
    )

    for value in (
        "https://127.0.0.1:18082",
        "http://localhost:18082",
        "http://127.0.0.1:18082/path",
        "http://retrostore.org",
    ):
        with pytest.raises(ValueError, match="127.0.0.1"):
            validate_loopback_candidate_url(value)


def test_pre_dns_bridge_preserves_method_query_body_and_approved_host() -> None:
    observed: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        observed.update(
            {
                "method": request.method,
                "url": str(request.url),
                "host": request.headers["host"],
                "body": request.content,
            }
        )
        return httpx.Response(
            200,
            headers={"Content-Type": "application/octet-stream"},
            content=b"response",
        )

    app, upstream = create_front_door_proxy_app(
        "http://34.102.211.182",
        "next.retrostore.org",
        transport=httpx.MockTransport(handle),
    )
    try:
        response = app.test_client().post("/api/listApps?page=1", data=b"request")
    finally:
        upstream.close()

    assert response.status_code == 200
    assert response.data == b"response"
    assert response.content_type == "application/octet-stream"
    assert observed == {
        "method": "POST",
        "url": "http://34.102.211.182/api/listApps?page=1",
        "host": "next.retrostore.org",
        "body": b"request",
    }

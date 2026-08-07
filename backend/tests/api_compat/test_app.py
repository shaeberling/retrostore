from pathlib import Path

import pytest
from flask import Response

from retrostore.api_compat.storage import InMemoryCompatibilityStorage
from retrostore.generated import ApiProtos_pb2 as api_pb
from retrostore.mirror import import_catalog_mirror
from services.api_compat.app import (
    create_app,
    create_archive_app,
    create_cloud_app,
    create_representative_app,
)
from tests.mirror.test_archive import _write_archive
from tests.mirror.test_persistence import MemoryObjectStore, MemorySnapshotStore, _mirror


def test_liveness_is_independent_of_implementation_readiness() -> None:
    client = create_app({"TESTING": True}).test_client()

    assert client.get("/health").status_code == 200
    readiness = client.get("/readyz")
    assert readiness.status_code == 503
    assert len(readiness.get_json()["missing_methods"]) == 9


def test_unknown_method_preserves_legacy_error_shape() -> None:
    client = create_app({"TESTING": True}).test_client()

    response = client.post("/api/doesNotExist", data=b"")

    assert response.status_code == 400
    assert response.data == b"RPC method 'doesNotExist' not found."
    assert response.content_type.startswith("text/plain")


def test_known_but_unimplemented_method_fails_closed() -> None:
    client = create_app({"TESTING": True}).test_client()

    response = client.post("/api/getApp", data=b"")

    assert response.status_code == 503
    assert b"not implemented" in response.data


def test_injected_handler_receives_the_unmodified_body() -> None:
    received = []

    def handler(body: bytes) -> Response:
        received.append(body)
        return Response(b"protobuf", mimetype="application/octet-stream")

    client = create_app(
        {"TESTING": True, "RETROSTORE_API_HANDLERS": {"getApp": handler}}
    ).test_client()

    response = client.post("/api/getApp", data=b"\x0a\x03abc")

    assert response.status_code == 200
    assert response.data == b"protobuf"
    assert received == [b"\x0a\x03abc"]


def test_representative_candidate_has_all_handlers() -> None:
    client = create_representative_app({"TESTING": True}).test_client()

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.get_json() == {"ready": True, "missing_methods": []}


def test_archive_candidate_loads_only_from_explicit_verified_path(tmp_path: Path) -> None:
    archive = tmp_path / "catalog.zip"
    _write_archive(archive)
    client = create_archive_app(archive, {"TESTING": True}).test_client()

    readiness = client.get("/readyz")
    response = client.post(
        "/api/getApp",
        data=api_pb.GetAppParams(app_id="app-1").SerializeToString(),
    )
    app_response = api_pb.ApiResponseApps.FromString(response.data)

    assert readiness.status_code == 200
    assert app_response.success is True
    assert app_response.app[0].name == "Armored Patrol"
    assert app_response.app[0].screenshot_url == ["https://legacy.example/shot-1"]


def test_cloud_candidate_fails_closed_without_explicit_resource_names() -> None:
    with pytest.raises(RuntimeError, match="Cloud catalog configuration is missing"):
        create_cloud_app({"TESTING": True})


def test_cloud_candidate_loads_the_active_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    objects = MemoryObjectStore()
    snapshots = MemorySnapshotStore()

    import_catalog_mirror(_mirror(), objects, snapshots)
    monkeypatch.setattr(
        "retrostore.mirror.google_cloud.google_catalog_stores",
        lambda **kwargs: (objects, snapshots),
    )
    client = create_cloud_app(
        {
            "TESTING": True,
            "RETROSTORE_PROJECT": "trs-80",
            "RETROSTORE_CATALOG_DATABASE": "retrostore",
            "RETROSTORE_ASSETS_BUCKET": "trs-80-retrostore-assets",
            "RETROSTORE_STATE_STORAGE": InMemoryCompatibilityStorage(),
        }
    ).test_client()

    readiness = client.get("/readyz")
    response = client.post(
        "/api/getApp",
        data=api_pb.GetAppParams(app_id="app-1").SerializeToString(),
    )
    app_response = api_pb.ApiResponseApps.FromString(response.data)

    assert readiness.status_code == 200
    assert app_response.success is True
    assert app_response.app[0].name == "Armored Patrol"

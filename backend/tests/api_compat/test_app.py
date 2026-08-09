from pathlib import Path

import pytest
from flask import Response

from retrostore.api_compat.storage import InMemoryCompatibilityStorage
from retrostore.generated import ApiProtos_pb2 as api_pb
from retrostore.mirror import build_catalog_snapshot, import_catalog_mirror
from services.api_compat.app import (
    create_app,
    create_archive_app,
    create_cloud_app,
    create_representative_app,
)
from tests.mirror.test_archive import _write_archive
from tests.mirror.test_catalog import _manifest
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

    screenshot = client.get("/assets/screenshots/shot-1")
    assert screenshot.status_code == 200
    assert screenshot.data == b"screenshot"
    assert screenshot.content_type == "image/png"
    assert screenshot.cache_control.max_age == 31_536_000
    assert screenshot.cache_control.immutable is True
    assert screenshot.headers["X-Content-Type-Options"] == "nosniff"
    assert screenshot.headers["Access-Control-Allow-Origin"] == "*"


def test_new_screenshot_uses_the_immutable_candidate_route(tmp_path: Path) -> None:
    archive = tmp_path / "catalog.zip"
    manifest = _manifest()
    manifest["screenshots"][0]["legacy_serving_url"] = None  # type: ignore[index]
    _write_archive(archive, manifest=manifest)

    client = create_archive_app(
        archive,
        {
            "TESTING": True,
            "RETROSTORE_PUBLIC_ORIGIN": "https://preview.example.test/",
        },
    ).test_client()
    response = client.post(
        "/api/getApp",
        data=api_pb.GetAppParams(app_id="app-1").SerializeToString(),
    )

    app_response = api_pb.ApiResponseApps.FromString(response.data)
    assert app_response.app[0].screenshot_url == [
        "https://preview.example.test/s/shot-1"
    ]
    assert client.get("/s/shot-1").data == b"screenshot"


def test_candidate_rejects_a_public_origin_with_a_path(tmp_path: Path) -> None:
    archive = tmp_path / "catalog.zip"
    _write_archive(archive)

    with pytest.raises(RuntimeError, match=r"HTTP\(S\) origin"):
        create_archive_app(
            archive,
            {"RETROSTORE_PUBLIC_ORIGIN": "https://preview.example.test/path"},
        )


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


def test_cloud_preview_can_pin_a_staged_snapshot_without_activation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    objects = MemoryObjectStore()
    snapshots = MemorySnapshotStore()
    active = _mirror(name="Active")
    preview = _mirror(name="Private Preview")
    for snapshot_mirror in (active, preview):
        snapshot = build_catalog_snapshot(snapshot_mirror)
        for value in snapshot.objects:
            objects.put_verified(value)
        snapshots.stage(snapshot)
    active_snapshot = build_catalog_snapshot(active)
    preview_snapshot = build_catalog_snapshot(preview)
    snapshots.activate(active_snapshot.id, active_snapshot.manifest_sha256)
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
            "RETROSTORE_CATALOG_SNAPSHOT_ID": preview_snapshot.id,
            "RETROSTORE_CATALOG_SNAPSHOT_MANIFEST_SHA256": (
                preview_snapshot.manifest_sha256
            ),
            "RETROSTORE_STATE_STORAGE": InMemoryCompatibilityStorage(),
        }
    ).test_client()

    response = client.post(
        "/api/getApp",
        data=api_pb.GetAppParams(app_id="app-1").SerializeToString(),
    )
    app_response = api_pb.ApiResponseApps.FromString(response.data)

    assert app_response.app[0].name == "Private Preview"
    assert snapshots.active_id == active_snapshot.id


def test_cloud_preview_requires_a_complete_snapshot_pin() -> None:
    with pytest.raises(RuntimeError, match="both snapshot ID"):
        create_cloud_app(
            {
                "TESTING": True,
                "RETROSTORE_PROJECT": "trs-80",
                "RETROSTORE_CATALOG_DATABASE": "retrostore",
                "RETROSTORE_ASSETS_BUCKET": "trs-80-retrostore-assets",
                "RETROSTORE_CATALOG_SNAPSHOT_ID": "catalog-" + "a" * 64,
                "RETROSTORE_STATE_STORAGE": InMemoryCompatibilityStorage(),
            }
        )

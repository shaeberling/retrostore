from flask import Response

from services.api_compat.app import create_app, create_representative_app


def test_liveness_is_independent_of_implementation_readiness() -> None:
    client = create_app({"TESTING": True}).test_client()

    assert client.get("/healthz").status_code == 200
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

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.get_json() == {"ready": True, "missing_methods": []}

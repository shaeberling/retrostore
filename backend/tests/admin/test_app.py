from services.admin.app import create_app


def test_admin_shell_and_health_are_available() -> None:
    client = create_app({"TESTING": True}).test_client()

    assert client.get("/healthz").status_code == 200
    page = client.get("/admin")
    assert page.status_code == 200
    assert b"RetroStore Admin candidate" in page.data


def test_admin_is_not_ready_until_auth_and_persistence_are_configured() -> None:
    client = create_app({"TESTING": True}).test_client()

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.get_json() == {
        "ready": False,
        "checks": {"authentication": False, "persistence": False},
    }

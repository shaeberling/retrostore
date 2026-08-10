import json

from flask import Flask

from retrostore.observability import register_request_observability


def test_request_event_is_structured_bounded_and_trace_correlated(capsys) -> None:
    app = Flask(__name__)
    app.config.update(TESTING=True, RETROSTORE_PROJECT="trs-80")
    register_request_observability(app, service="test-service")

    @app.post("/secret/<secret_value>")
    def example(secret_value: str) -> tuple[str, int]:
        return "response-secret", 201

    response = app.test_client().post(
        "/secret/path-secret?token=query-secret",
        data=b"request-secret",
        headers={
            "X-Cloud-Trace-Context": "0123456789abcdef0123456789ABCDEF/123;o=1",
            "User-Agent": "private-agent",
        },
    )

    assert response.status_code == 201
    event = json.loads(capsys.readouterr().out)
    assert event == {
        "endpoint": "example",
        "event": "http_request",
        "httpRequest": {
            "latency": event["httpRequest"]["latency"],
            "requestMethod": "POST",
            "requestSize": "14",
            "responseSize": "15",
            "status": 201,
        },
        "logging.googleapis.com/trace": (
            "projects/trs-80/traces/0123456789abcdef0123456789abcdef"
        ),
        "service": "test-service",
        "severity": "INFO",
    }
    serialized = json.dumps(event)
    secrets = (
        "path-secret",
        "query-secret",
        "request-secret",
        "response-secret",
        "private-agent",
    )
    for secret in secrets:
        assert secret not in serialized


def test_request_logging_can_be_disabled(capsys) -> None:
    app = Flask(__name__)
    app.config["RETROSTORE_REQUEST_LOGGING"] = False
    register_request_observability(app, service="test-service")

    @app.get("/")
    def example() -> str:
        return "ok"

    assert app.test_client().get("/").status_code == 200
    assert capsys.readouterr().out == ""

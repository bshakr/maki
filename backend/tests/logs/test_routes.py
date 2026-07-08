from datetime import UTC, datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

from maki.main import app
from maki.schemas import LogEventItem, ServiceLogsResponse

_DEFAULT_EVENTS = [
    LogEventItem(
        timestamp=datetime(2026, 6, 5, 12, 0, tzinfo=UTC),
        message="hello",
        stream="stream-a",
    )
]


def _fake(error: str | None = None, events=None):
    return ServiceLogsResponse(
        log_group="/ecs/inventory-production",
        region="eu-west-1",
        events=_DEFAULT_EVENTS if events is None else events,
        truncated=False,
        error=error,
    )


def test_get_logs_endpoint_returns_events():
    with patch("maki.logs.routes.get_logs_service") as factory:
        factory.return_value.get_logs.return_value = _fake()
        client = TestClient(app)
        r = client.get("/api/services/inventory/logs")

    assert r.status_code == 200
    body = r.json()
    assert body["log_group"] == "/ecs/inventory-production"
    assert body["region"] == "eu-west-1"
    assert body["error"] is None
    assert body["events"][0]["message"] == "hello"
    assert body["events"][0]["stream"] == "stream-a"


def test_passes_query_params_with_defaults():
    with patch("maki.logs.routes.get_logs_service") as factory:
        factory.return_value.get_logs.return_value = _fake()
        client = TestClient(app)
        client.get("/api/services/inventory/logs")
        factory.return_value.get_logs.assert_called_once_with(
            "inventory", 200, 60, force=False
        )


def test_passes_query_params_explicit():
    with patch("maki.logs.routes.get_logs_service") as factory:
        factory.return_value.get_logs.return_value = _fake()
        client = TestClient(app)
        client.get("/api/services/inventory/logs?limit=50&since_minutes=30&refresh=1")
        factory.return_value.get_logs.assert_called_once_with(
            "inventory", 50, 30, force=True
        )


def test_not_found_error_is_200_with_typed_error():
    with patch("maki.logs.routes.get_logs_service") as factory:
        factory.return_value.get_logs.return_value = _fake(error="not_found", events=[])
        client = TestClient(app)
        r = client.get("/api/services/missing/logs")

    assert r.status_code == 200
    body = r.json()
    assert body["error"] == "not_found"
    assert body["events"] == []


def test_forbidden_error_is_200_with_typed_error():
    with patch("maki.logs.routes.get_logs_service") as factory:
        factory.return_value.get_logs.return_value = _fake(error="forbidden", events=[])
        client = TestClient(app)
        r = client.get("/api/services/inventory/logs")

    assert r.status_code == 200
    assert r.json()["error"] == "forbidden"


def test_limit_out_of_range_is_422():
    client = TestClient(app)
    assert client.get("/api/services/inventory/logs?limit=0").status_code == 422
    assert client.get("/api/services/inventory/logs?limit=5000").status_code == 422
    assert client.get("/api/services/inventory/logs?since_minutes=0").status_code == 422

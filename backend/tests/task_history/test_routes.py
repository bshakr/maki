from datetime import UTC, datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

from maki.main import app
from maki.schemas import TaskHistoryPoint, TaskHistoryResponse


def _fake():
    return TaskHistoryResponse(
        service="inventory",
        range_days=30,
        period_seconds=3600,
        points=[
            TaskHistoryPoint(
                timestamp=datetime(2026, 5, 30, 10, 0, tzinfo=UTC), running=2, desired=3
            )
        ],
        generated_at=datetime(2026, 5, 31, tzinfo=UTC),
    )


def test_get_task_history_endpoint():
    with patch("maki.task_history.routes.get_task_history_service") as factory:
        factory.return_value.get_task_history.return_value = _fake()
        client = TestClient(app)
        r = client.get("/api/services/inventory/task-history")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "inventory"
    assert body["period_seconds"] == 3600
    assert body["points"][0]["running"] == 2
    assert body["points"][0]["desired"] == 3


def test_passes_query_params_with_defaults():
    with patch("maki.task_history.routes.get_task_history_service") as factory:
        factory.return_value.get_task_history.return_value = _fake()
        client = TestClient(app)
        client.get("/api/services/inventory/task-history")
        factory.return_value.get_task_history.assert_called_once_with("inventory", 30, force=False)


def test_passes_query_params_explicit():
    with patch("maki.task_history.routes.get_task_history_service") as factory:
        factory.return_value.get_task_history.return_value = _fake()
        client = TestClient(app)
        client.get("/api/services/inventory/task-history?range_days=7&refresh=1")
        factory.return_value.get_task_history.assert_called_once_with("inventory", 7, force=True)

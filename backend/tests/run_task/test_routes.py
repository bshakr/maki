from fastapi.testclient import TestClient

from maki.main import app


def test_run_task_is_inert_preview():
    client = TestClient(app)
    r = client.post(
        "/api/services/newsfeed/run-task",
        json={
            "command": "python -m scripts.backfill --since 2026-05-01",
            "task_def": "newsfeed:1987",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["executed"] is False
    assert body["service"] == "newsfeed"
    assert body["command"] == "python -m scripts.backfill --since 2026-05-01"
    assert body["task_def"] == "newsfeed:1987"
    assert "preview only" in body["message"].lower()
    assert "no production change" in body["message"].lower()


def test_run_task_task_def_defaults_to_null():
    client = TestClient(app)
    r = client.post(
        "/api/services/wfm-service/run-task",
        json={"command": "echo hi"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["task_def"] is None
    assert body["executed"] is False
    assert body["service"] == "wfm-service"
    assert body["command"] == "echo hi"

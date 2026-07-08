from fastapi.testclient import TestClient

from maki.main import app


def test_rollback_is_inert_preview():
    client = TestClient(app)
    r = client.post("/api/services/wfm-service/rollback", json={"target_sha": "abc123"})
    assert r.status_code == 200
    body = r.json()
    assert body["executed"] is False
    assert body["service"] == "wfm-service"
    assert body["target_sha"] == "abc123"
    assert "no production change" in body["message"].lower()

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from maki.db.repository import DeployEventRepository, ServiceWatchRepository
from maki.main import app
from maki.watches.service import WatchesService

client = TestClient(app)


def _install_service(monkeypatch, session_factory):
    service = WatchesService(
        watches=ServiceWatchRepository(),
        deploys=DeployEventRepository(),
        session_factory=session_factory,
    )
    monkeypatch.setattr("maki.watches.routes.get_watches_service", lambda: service)


def _seed_service(session, name: str) -> None:
    DeployEventRepository().upsert_many(
        session,
        [
            {
                "service": name,
                "platform": "ecs",
                "revision": 1,
                "sha": "abc1234",
                "image": None,
                "registered_at": datetime(2026, 9, 1, tzinfo=UTC),
                "committed_at": None,
                "finished_at": None,
                "author": None,
                "author_avatar_url": None,
                "message": None,
                "commit_url": None,
                "pr_url": None,
                "status": "success",
                "is_rollback": False,
            }
        ],
    )
    session.flush()


def test_list_is_empty_initially(session_factory, monkeypatch):
    _install_service(monkeypatch, session_factory)
    r = client.get("/api/watches")
    assert r.status_code == 200
    assert r.json() == {"watches": []}


def test_add_then_list(session, session_factory, monkeypatch):
    _seed_service(session, "insights")
    _install_service(monkeypatch, session_factory)
    r = client.post("/api/watches", json={"service": "insights"})
    assert r.status_code == 201
    assert r.json()["service"] == "insights"
    assert [w["service"] for w in client.get("/api/watches").json()["watches"]] == ["insights"]


def test_add_unknown_service_is_404(session, session_factory, monkeypatch):
    _install_service(monkeypatch, session_factory)
    r = client.post("/api/watches", json={"service": "nope"})
    assert r.status_code == 404
    assert "deploy history" in r.json()["detail"]


def test_delete_returns_204(session, session_factory, monkeypatch):
    _seed_service(session, "insights")
    _install_service(monkeypatch, session_factory)
    client.post("/api/watches", json={"service": "insights"})
    assert client.delete("/api/watches/insights").status_code == 204
    assert client.get("/api/watches").json() == {"watches": []}


def test_delete_unknown_service_is_404(session_factory, monkeypatch):
    _install_service(monkeypatch, session_factory)
    assert client.delete("/api/watches/nope").status_code == 404

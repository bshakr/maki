from datetime import UTC, datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

from maki.activity.cursor import encode_cursor
from maki.main import app
from maki.schemas import DeploymentsResponse, DeployRecord


def test_get_deployments_endpoint():
    fake = DeploymentsResponse(
        service="newsfeed",
        deployments=[DeployRecord(id=1, sha="abc", revision=5, author="bailey")],
        generated_at=datetime(2026, 5, 31, tzinfo=UTC),
    )
    with patch("maki.history.routes.get_history_service") as factory:
        factory.return_value.get_deployments_page.return_value = fake
        client = TestClient(app)
        r = client.get("/api/services/newsfeed/deployments")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "newsfeed"
    assert body["deployments"][0]["sha"] == "abc"
    assert body["deployments"][0]["author"] == "bailey"


def test_refresh_query_forces_recompute():
    fake = DeploymentsResponse(
        service="newsfeed", deployments=[], generated_at=datetime(2026, 5, 31, tzinfo=UTC)
    )
    with patch("maki.history.routes.get_history_service") as factory:
        factory.return_value.get_deployments_page.return_value = fake
        client = TestClient(app)
        client.get("/api/services/newsfeed/deployments?refresh=1")
        factory.return_value.get_deployments_page.assert_called_once_with(
            "newsfeed", cursor=None, force=True
        )


def test_default_does_not_force():
    fake = DeploymentsResponse(
        service="newsfeed", deployments=[], generated_at=datetime(2026, 5, 31, tzinfo=UTC)
    )
    with patch("maki.history.routes.get_history_service") as factory:
        factory.return_value.get_deployments_page.return_value = fake
        client = TestClient(app)
        client.get("/api/services/newsfeed/deployments")
        factory.return_value.get_deployments_page.assert_called_once_with(
            "newsfeed", cursor=None, force=False
        )


def test_cursor_query_decodes_and_passes_keyset():
    fake = DeploymentsResponse(
        service="newsfeed", deployments=[], generated_at=datetime(2026, 5, 31, tzinfo=UTC)
    )
    at = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    cursor = encode_cursor(at, 42)
    with patch("maki.history.routes.get_history_service") as factory:
        factory.return_value.get_deployments_page.return_value = fake
        client = TestClient(app)
        client.get(f"/api/services/newsfeed/deployments?cursor={cursor}")
        factory.return_value.get_deployments_page.assert_called_once_with(
            "newsfeed", cursor=(at, 42), force=False
        )


def test_invalid_cursor_returns_422():
    with patch("maki.history.routes.get_history_service"):
        client = TestClient(app)
        r = client.get("/api/services/newsfeed/deployments?cursor=not-a-real-cursor")
    assert r.status_code == 422


def test_get_deploy_endpoint_returns_record():
    fake = DeployRecord(id=1, sha="af0968fabc123", revision=5, author="bailey")
    with patch("maki.history.routes.get_history_service") as factory:
        factory.return_value.get_deploy.return_value = fake
        client = TestClient(app)
        r = client.get("/api/services/newsfeed/deploys/af0968f")
    assert r.status_code == 200
    body = r.json()
    assert body["sha"] == "af0968fabc123"
    assert body["author"] == "bailey"
    factory.return_value.get_deploy.assert_called_once_with("newsfeed", "af0968f")


def test_get_deploy_endpoint_returns_404_when_not_found():
    with patch("maki.history.routes.get_history_service") as factory:
        factory.return_value.get_deploy.return_value = None
        client = TestClient(app)
        r = client.get("/api/services/newsfeed/deploys/deadbee")
    assert r.status_code == 404

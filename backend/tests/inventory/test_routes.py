from datetime import UTC, datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

from maki.main import app
from maki.schemas import DeployedService, ServicesResponse


def test_get_services_returns_inventory():
    fake = ServicesResponse(
        services=[DeployedService(name="newsfeed", platform="ecs", git_sha="abc")],
        generated_at=datetime(2026, 5, 29, tzinfo=UTC),
    )
    with patch("maki.inventory.routes.get_inventory_service") as factory:
        factory.return_value.get_inventory.return_value = fake
        client = TestClient(app)
        r = client.get("/api/services")
    assert r.status_code == 200
    assert r.json()["services"][0]["name"] == "newsfeed"
    assert r.json()["services"][0]["git_sha"] == "abc"


def test_get_services_serializes_new_ecs_fields():
    fake = ServicesResponse(
        services=[
            DeployedService(
                name="newsfeed",
                platform="ecs",
                git_sha="abc",
                version="v1.2.3-abc",
                region="eu-west-1",
                rollout_progress=50.0,
                rollout_reason="ECS deployment in progress.",
                cpu_reservation=256,
                mem_reservation=512,
            )
        ],
        generated_at=datetime(2026, 5, 29, tzinfo=UTC),
    )
    with patch("maki.inventory.routes.get_inventory_service") as factory:
        factory.return_value.get_inventory.return_value = fake
        client = TestClient(app)
        r = client.get("/api/services")
    assert r.status_code == 200
    svc = r.json()["services"][0]
    assert svc["version"] == "v1.2.3-abc"
    assert svc["region"] == "eu-west-1"
    assert svc["rollout_progress"] == 50.0
    assert svc["rollout_reason"] == "ECS deployment in progress."
    assert svc["cpu_reservation"] == 256
    assert svc["mem_reservation"] == 512


def test_new_fields_default_to_none():
    # Amplify (and any non-ECS) rows leave the new ECS fields as their None defaults.
    fake = ServicesResponse(
        services=[DeployedService(name="web-app", platform="amplify")],
        generated_at=datetime(2026, 5, 29, tzinfo=UTC),
    )
    with patch("maki.inventory.routes.get_inventory_service") as factory:
        factory.return_value.get_inventory.return_value = fake
        client = TestClient(app)
        r = client.get("/api/services")
    svc = r.json()["services"][0]
    assert svc["version"] is None
    assert svc["region"] is None
    assert svc["rollout_progress"] is None
    assert svc["rollout_reason"] is None
    assert svc["cpu_reservation"] is None
    assert svc["mem_reservation"] is None


def test_refresh_query_forces_recompute():
    fake = ServicesResponse(services=[], generated_at=datetime(2026, 5, 31, tzinfo=UTC))
    with patch("maki.inventory.routes.get_inventory_service") as factory:
        factory.return_value.get_inventory.return_value = fake
        client = TestClient(app)
        client.get("/api/services?refresh=1")
        factory.return_value.get_inventory.assert_called_once_with(force=True)


def test_default_does_not_force():
    fake = ServicesResponse(services=[], generated_at=datetime(2026, 5, 31, tzinfo=UTC))
    with patch("maki.inventory.routes.get_inventory_service") as factory:
        factory.return_value.get_inventory.return_value = fake
        client = TestClient(app)
        client.get("/api/services")
        factory.return_value.get_inventory.assert_called_once_with(force=False)

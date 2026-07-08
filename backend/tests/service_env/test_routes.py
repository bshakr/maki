from datetime import UTC, datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

from maki.main import app
from maki.schemas import ContainerEnv, EnvVar, SecretRef, ServiceEnvResponse


def _fake():
    return ServiceEnvResponse(
        service="inventory",
        task_def="inventory:42",
        containers=[
            ContainerEnv(
                name="app",
                environment=[EnvVar(name="LOG_LEVEL", value="info")],
                secrets=[SecretRef(name="DB_PASSWORD", value_from="arn:ssm:db")],
            )
        ],
        generated_at=datetime(2026, 5, 31, tzinfo=UTC),
    )


def test_get_service_env_endpoint():
    with patch("maki.service_env.routes.get_service_env_service") as factory:
        factory.return_value.get_env.return_value = _fake()
        client = TestClient(app)
        r = client.get("/api/services/inventory/env")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "inventory"
    assert body["task_def"] == "inventory:42"
    container = body["containers"][0]
    assert container["environment"][0] == {"name": "LOG_LEVEL", "value": "info"}
    secret = container["secrets"][0]
    assert secret == {"name": "DB_PASSWORD", "value_from": "arn:ssm:db"}
    assert "value" not in secret  # secret refs never carry a value


def test_passes_service_name():
    with patch("maki.service_env.routes.get_service_env_service") as factory:
        factory.return_value.get_env.return_value = _fake()
        client = TestClient(app)
        client.get("/api/services/inventory/env")
        # No refresh/force param — env is never cached, so every request is fresh.
        factory.return_value.get_env.assert_called_once_with("inventory")

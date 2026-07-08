from datetime import UTC, datetime
from unittest.mock import MagicMock

from maki.service_env.service import ServiceEnvService

NOW = datetime(2026, 5, 31, 12, 0, tzinfo=UTC)


def _task_def(raw):
    td = MagicMock()
    td.current_env.return_value = raw
    return td


def _service(task_def):
    return ServiceEnvService(task_def=task_def, now=lambda: NOW)


def _raw():
    return {
        "task_def": "inventory:42",
        "containers": [
            {
                "name": "app",
                "environment": [{"name": "LOG_LEVEL", "value": "info"}],
                "secrets": [{"name": "DB_PASSWORD", "value_from": "arn:ssm:db"}],
            }
        ],
    }


def test_maps_raw_into_response():
    resp = _service(_task_def(_raw())).get_env("inventory")

    assert resp.service == "inventory"
    assert resp.task_def == "inventory:42"
    assert resp.generated_at == NOW
    assert len(resp.containers) == 1
    container = resp.containers[0]
    assert container.name == "app"
    assert container.environment[0].name == "LOG_LEVEL"
    assert container.environment[0].value == "info"
    assert container.secrets[0].name == "DB_PASSWORD"
    assert container.secrets[0].value_from == "arn:ssm:db"
    # Secret schema carries no value field at all.
    assert not hasattr(container.secrets[0], "value")


def test_env_var_without_a_value_does_not_raise():
    # ECS allows an env entry with no value; building the response must not 500 (it runs on the
    # blocking cache path, outside the wrapper's try/except).
    raw = {
        "task_def": "inventory:42",
        "containers": [
            {"name": "app", "environment": [{"name": "EMPTY", "value": None}], "secrets": []}
        ],
    }
    resp = _service(_task_def(raw)).get_env("inventory")
    assert resp.containers[0].environment[0].name == "EMPTY"
    assert resp.containers[0].environment[0].value is None


def test_none_from_wrapper_is_valid_empty_response():
    resp = _service(_task_def(None)).get_env("inventory")

    assert resp.service == "inventory"
    assert resp.task_def is None
    assert resp.containers == []
    assert resp.generated_at == NOW


def test_not_cached_fetches_fresh_every_call():
    # Env values can be plaintext secrets, so the service must NEVER retain them — every call
    # hits ECS fresh (no SwrCache holding values in process memory).
    task_def = _task_def(_raw())
    svc = _service(task_def)

    svc.get_env("inventory")
    svc.get_env("inventory")
    assert task_def.current_env.call_count == 2  # no caching — fetched fresh each time

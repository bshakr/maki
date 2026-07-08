from unittest.mock import MagicMock

from maki.aws.task_definition import ECSTaskDefinition

ARN = "arn:aws:ecs:eu-west-1:123:task-definition/inventory:42"


def _client(*, services, task_def):
    client = MagicMock()
    client.describe_services.return_value = {"services": services}
    client.describe_task_definition.return_value = {"taskDefinition": task_def}
    return client


def _td(containers):
    return {"containerDefinitions": containers}


def test_maps_env_and_secret_refs_and_derives_task_def():
    client = _client(
        services=[{"taskDefinition": ARN}],
        task_def=_td(
            [
                {
                    "name": "app",
                    "environment": [
                        {"name": "LOG_LEVEL", "value": "info"},
                        {"name": "REGION", "value": "eu-west-1"},
                    ],
                    "secrets": [
                        {
                            "name": "DB_PASSWORD",
                            "valueFrom": "arn:aws:ssm:eu-west-1:123:parameter/db/pw",
                        }
                    ],
                }
            ]
        ),
    )
    result = ECSTaskDefinition(client, "production").current_env("inventory")

    assert result is not None
    assert result["task_def"] == "inventory:42"
    assert len(result["containers"]) == 1
    container = result["containers"][0]
    assert container["name"] == "app"
    assert container["environment"] == [
        {"name": "LOG_LEVEL", "value": "info"},
        {"name": "REGION", "value": "eu-west-1"},
    ]
    assert container["secrets"] == [
        {"name": "DB_PASSWORD", "value_from": "arn:aws:ssm:eu-west-1:123:parameter/db/pw"}
    ]
    client.describe_services.assert_called_once_with(cluster="production", services=["inventory"])


def test_secret_never_carries_a_value():
    # describe_task_definition only ever returns a reference; even if a stray "value" key
    # appeared on a secret, the wrapper must surface only the ref, never a value.
    client = _client(
        services=[{"taskDefinition": ARN}],
        task_def=_td(
            [
                {
                    "name": "app",
                    "environment": [],
                    "secrets": [
                        {
                            "name": "API_KEY",
                            "valueFrom": "arn:aws:secretsmanager:eu-west-1:123:secret:api",
                            "value": "should-never-surface",
                        }
                    ],
                }
            ]
        ),
    )
    result = ECSTaskDefinition(client, "production").current_env("inventory")

    secret = result["containers"][0]["secrets"][0]
    assert "value" not in secret
    assert set(secret.keys()) == {"name", "value_from"}
    # We never resolve the ref against SSM/Secrets Manager.
    assert client.method_calls  # only describe_* were called
    called = {c[0] for c in client.method_calls}
    assert called == {"describe_services", "describe_task_definition"}


def test_groups_multiple_containers():
    client = _client(
        services=[{"taskDefinition": ARN}],
        task_def=_td(
            [
                {
                    "name": "app",
                    "environment": [{"name": "A", "value": "1"}],
                    "secrets": [],
                },
                {
                    "name": "sidecar",
                    "environment": [{"name": "B", "value": "2"}],
                    "secrets": [{"name": "TOKEN", "valueFrom": "arn:ref"}],
                },
            ]
        ),
    )
    result = ECSTaskDefinition(client, "production").current_env("inventory")

    assert [c["name"] for c in result["containers"]] == ["app", "sidecar"]
    assert result["containers"][1]["secrets"][0]["value_from"] == "arn:ref"


def test_no_services_returns_none():
    client = _client(services=[], task_def=_td([]))
    assert ECSTaskDefinition(client, "production").current_env("inventory") is None
    client.describe_task_definition.assert_not_called()


def test_missing_task_definition_arn_returns_none():
    client = _client(services=[{}], task_def=_td([]))
    assert ECSTaskDefinition(client, "production").current_env("inventory") is None


def test_fail_soft_on_describe_error_returns_none():
    client = MagicMock()
    client.describe_services.side_effect = RuntimeError("boom")
    assert ECSTaskDefinition(client, "production").current_env("inventory") is None


def _awslogs(group, region="eu-west-1"):
    return {"logDriver": "awslogs", "options": {"awslogs-group": group, "awslogs-region": region}}


def test_log_group_resolves_awslogs_group_and_region():
    client = _client(
        services=[{"taskDefinition": ARN}],
        task_def=_td(
            [{"name": "app", "logConfiguration": _awslogs("/ecs/inventory", "eu-west-2")}]
        ),
    )
    assert ECSTaskDefinition(client, "production").log_group("inventory") == (
        "/ecs/inventory",
        "eu-west-2",
    )


def test_log_group_prefers_container_matching_service_name():
    client = _client(
        services=[{"taskDefinition": ARN}],
        task_def=_td(
            [
                {"name": "log-router", "logConfiguration": _awslogs("/ecs/sidecar")},
                {"name": "inventory", "logConfiguration": _awslogs("/ecs/inventory-real")},
            ]
        ),
    )
    group, _ = ECSTaskDefinition(client, "production").log_group("inventory")
    assert group == "/ecs/inventory-real"


def test_log_group_falls_back_to_first_container_with_awslogs():
    client = _client(
        services=[{"taskDefinition": ARN}],
        task_def=_td(
            [
                {"name": "app", "logConfiguration": _awslogs("/ecs/app-real")},
                {"name": "sidecar", "logConfiguration": _awslogs("/ecs/sidecar")},
            ]
        ),
    )
    # No container name matches the service -> first one with an awslogs group wins.
    group, _ = ECSTaskDefinition(client, "production").log_group("inventory")
    assert group == "/ecs/app-real"


def test_log_group_skips_non_awslogs_drivers():
    client = _client(
        services=[{"taskDefinition": ARN}],
        task_def=_td(
            [
                {"name": "router", "logConfiguration": {"logDriver": "awsfirelens", "options": {}}},
                {"name": "inventory", "logConfiguration": _awslogs("/ecs/inventory-real")},
            ]
        ),
    )
    group, _ = ECSTaskDefinition(client, "production").log_group("inventory")
    assert group == "/ecs/inventory-real"


def test_log_group_no_awslogs_config_returns_none():
    client = _client(
        services=[{"taskDefinition": ARN}],
        task_def=_td([{"name": "app", "logConfiguration": {"logDriver": "json-file"}}]),
    )
    assert ECSTaskDefinition(client, "production").log_group("inventory") is None


def test_log_group_no_log_configuration_returns_none():
    client = _client(
        services=[{"taskDefinition": ARN}],
        task_def=_td([{"name": "app"}]),
    )
    assert ECSTaskDefinition(client, "production").log_group("inventory") is None


def test_log_group_no_services_returns_none():
    client = _client(services=[], task_def=_td([]))
    assert ECSTaskDefinition(client, "production").log_group("inventory") is None
    client.describe_task_definition.assert_not_called()


def test_log_group_fail_soft_on_aws_error_returns_none():
    client = MagicMock()
    client.describe_services.side_effect = RuntimeError("boom")
    assert ECSTaskDefinition(client, "production").log_group("inventory") is None

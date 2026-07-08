from datetime import UTC, datetime
from unittest.mock import MagicMock

from maki.aws.ecs_registry import ECSDeployRegistry


def _client_with(services, task_defs):
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [
        {"serviceArns": [s["serviceArn"] for s in services]}
    ]
    client.describe_services.return_value = {"services": services}
    client.describe_task_definition.side_effect = lambda taskDefinition: {
        "taskDefinition": task_defs[taskDefinition]
    }
    return client


def test_returns_deployed_service_with_git_sha_and_counts():
    deployed_at = datetime(2026, 5, 29, 9, 0, tzinfo=UTC)
    services = [
        {
            "serviceArn": "arn:aws:ecs:eu-west-1:1:service/production/newsfeed",
            "serviceName": "newsfeed",
            "runningCount": 2,
            "desiredCount": 2,
            "taskDefinition": "arn:td:newsfeed:5",
            "deployments": [
                {
                    "rolloutState": "COMPLETED",
                    "pendingCount": 0,
                    "updatedAt": deployed_at,
                    "taskDefinition": "arn:td:newsfeed:5",
                }
            ],
        }
    ]
    task_defs = {
        "arn:td:newsfeed:5": {
            "containerDefinitions": [
                {"image": "527.dkr.ecr.eu-west-1.amazonaws.com/newsfeed:abc123sha"}
            ]
        }
    }
    registry = ECSDeployRegistry(_client_with(services, task_defs), cluster="production")
    result = registry.list_deployed_services()
    assert len(result) == 1
    svc = result[0]
    assert svc.name == "newsfeed"
    assert svc.platform == "ecs"
    assert svc.git_sha == "abc123sha"
    assert svc.running_count == 2
    assert svc.desired_count == 2
    assert svc.pending_count == 0
    assert svc.status == "COMPLETED"
    assert svc.deployed_at == deployed_at


def test_exposes_version_region_rollout_and_reservations():
    deployed_at = datetime(2026, 5, 29, 9, 0, tzinfo=UTC)
    services = [
        {
            "serviceArn": "arn:aws:ecs:eu-west-1:1:service/production/newsfeed",
            "serviceName": "newsfeed",
            "runningCount": 1,
            "desiredCount": 4,
            "taskDefinition": "arn:td:newsfeed:5",
            "deployments": [
                {
                    "status": "PRIMARY",
                    "rolloutState": "IN_PROGRESS",
                    "rolloutStateReason": "ECS deployment ecs-svc/123 in progress.",
                    "pendingCount": 1,
                    "updatedAt": deployed_at,
                    "taskDefinition": "arn:td:newsfeed:5",
                }
            ],
        }
    ]
    task_defs = {
        "arn:td:newsfeed:5": {
            "containerDefinitions": [
                {
                    "image": "527.dkr.ecr.eu-west-1.amazonaws.com/newsfeed:v2.3.1-abc123sha",
                    "cpu": 256,
                    "memory": 512,
                }
            ]
        }
    }
    registry = ECSDeployRegistry(
        _client_with(services, task_defs), cluster="production", region="eu-west-1"
    )
    svc = registry.list_deployed_services()[0]
    assert svc.version == "v2.3.1-abc123sha"  # full tag, not just the short sha
    assert svc.git_sha == "v2.3.1-abc123sha"
    assert svc.region == "eu-west-1"
    assert svc.rollout_reason == "ECS deployment ecs-svc/123 in progress."
    assert svc.rollout_progress == 25.0  # 1 / 4 * 100
    assert svc.cpu_reservation == 256
    assert svc.mem_reservation == 512


def test_reservation_falls_back_to_task_level_cpu_memory():
    # Real Fargate/EC2 task defs declare cpu/memory at the TASK level (as
    # strings) and leave the container values unset — we must read those.
    services = [
        {
            "serviceArn": "arn:aws:ecs:eu-west-1:1:service/production/api",
            "serviceName": "api",
            "runningCount": 2,
            "desiredCount": 2,
            "taskDefinition": "arn:td:api:7",
            "deployments": [
                {"status": "PRIMARY", "taskDefinition": "arn:td:api:7"}
            ],
        }
    ]
    task_defs = {
        "arn:td:api:7": {
            "cpu": "1024",
            "memory": "2048",
            "containerDefinitions": [{"image": "r/api:sha"}],  # no container cpu/memory
        }
    }
    registry = ECSDeployRegistry(
        _client_with(services, task_defs), cluster="production", region="eu-west-1"
    )
    svc = registry.list_deployed_services()[0]
    assert svc.cpu_reservation == 1024  # parsed from the task-level string
    assert svc.mem_reservation == 2048


def test_rollout_progress_is_none_when_desired_is_zero_or_missing():
    services = [
        {
            "serviceArn": "arn:aws:ecs:eu-west-1:1:service/production/idle",
            "serviceName": "idle",
            "runningCount": 0,
            "desiredCount": 0,
            "taskDefinition": "arn:td:idle:1",
            "deployments": [
                {"status": "PRIMARY", "taskDefinition": "arn:td:idle:1"},
            ],
        }
    ]
    task_defs = {"arn:td:idle:1": {"containerDefinitions": [{"image": "r/idle:sha"}]}}
    registry = ECSDeployRegistry(
        _client_with(services, task_defs), cluster="production", region="eu-west-1"
    )
    svc = registry.list_deployed_services()[0]
    assert svc.rollout_progress is None


def test_new_fields_are_none_safe_when_absent():
    # No rolloutStateReason, no cpu/memory on the container, no region configured.
    services = [
        {
            "serviceArn": "arn:aws:ecs:eu-west-1:1:service/production/bare",
            "serviceName": "bare",
            "runningCount": 2,
            "desiredCount": 2,
            "taskDefinition": "arn:td:bare:1",
            "deployments": [
                {"status": "PRIMARY", "taskDefinition": "arn:td:bare:1"},
            ],
        }
    ]
    task_defs = {"arn:td:bare:1": {"containerDefinitions": [{"image": "r/bare:sha"}]}}
    registry = ECSDeployRegistry(_client_with(services, task_defs), cluster="production")
    svc = registry.list_deployed_services()[0]
    assert svc.region is None
    assert svc.rollout_reason is None
    assert svc.cpu_reservation is None
    assert svc.mem_reservation is None
    assert svc.rollout_progress == 100.0  # 2 / 2 * 100


def test_digest_pinned_image_has_no_version():
    client = _one_service("527.dkr.ecr.eu-west-1.amazonaws.com/api@sha256:deadbeef")
    svc = ECSDeployRegistry(client, cluster="production").list_deployed_services()[0]
    assert svc.version is None


def test_captures_pending_count_when_rollout_state_absent():
    # A mid-deploy service without rollout tracking: rolloutState null, tasks
    # still launching (pendingCount > 0). We must capture pendingCount so the UI
    # reads it as "deploying", not "degraded".
    services = [
        {
            "serviceArn": "arn:aws:ecs:eu-west-1:1:service/production/prod-schedule-versioning",
            "serviceName": "prod-schedule-versioning",
            "runningCount": 0,
            "desiredCount": 2,
            "taskDefinition": "arn:td:sv:9",
            "deployments": [
                {"pendingCount": 2, "taskDefinition": "arn:td:sv:9"},
            ],
        }
    ]
    task_defs = {"arn:td:sv:9": {"containerDefinitions": [{"image": "x/sv:deadbeef"}]}}
    registry = ECSDeployRegistry(_client_with(services, task_defs), cluster="production")
    svc = registry.list_deployed_services()[0]
    assert svc.running_count == 0
    assert svc.desired_count == 2
    assert svc.pending_count == 2
    assert svc.status is None  # no rolloutState reported


def test_describe_services_is_batched_in_tens():
    arns = [f"arn:svc-{i}" for i in range(23)]
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [{"serviceArns": arns}]
    client.describe_services.return_value = {"services": []}
    client.describe_task_definition.return_value = {"taskDefinition": {"containerDefinitions": []}}
    registry = ECSDeployRegistry(client, cluster="production")
    registry.list_deployed_services()
    assert client.describe_services.call_count == 3


def test_selects_primary_deployment_over_active():
    deployed_at = datetime(2026, 5, 29, 9, 0, tzinfo=UTC)
    services = [
        {
            "serviceArn": "arn:aws:ecs:eu-west-1:1:service/production/api",
            "serviceName": "api",
            "runningCount": 1,
            "desiredCount": 1,
            "taskDefinition": "arn:td:api:9",
            "deployments": [
                {
                    "status": "ACTIVE",
                    "rolloutState": "IN_PROGRESS",
                    "updatedAt": datetime(2026, 5, 29, 7, 0, tzinfo=UTC),
                    "taskDefinition": "arn:td:api:8",
                },
                {
                    "status": "PRIMARY",
                    "rolloutState": "COMPLETED",
                    "updatedAt": deployed_at,
                    "taskDefinition": "arn:td:api:9",
                },
            ],
        }
    ]
    task_defs = {
        "arn:td:api:8": {"containerDefinitions": [{"image": "r/api:oldsha"}]},
        "arn:td:api:9": {"containerDefinitions": [{"image": "r/api:newsha"}]},
    }
    svc = ECSDeployRegistry(
        _client_with(services, task_defs), cluster="production"
    ).list_deployed_services()[0]
    assert svc.git_sha == "newsha"
    assert svc.status == "COMPLETED"
    assert svc.deployed_at == deployed_at


def _one_service(image, td="arn:td:api:1"):
    services = [
        {
            "serviceArn": "arn:aws:ecs:eu-west-1:1:service/production/api",
            "serviceName": "api",
            "runningCount": 1,
            "desiredCount": 1,
            "taskDefinition": td,
            "deployments": [
                {
                    "status": "PRIMARY",
                    "rolloutState": "COMPLETED",
                    "updatedAt": datetime(2026, 5, 29, tzinfo=UTC),
                    "taskDefinition": td,
                }
            ],
        }
    ]
    return _client_with(services, {td: {"containerDefinitions": [{"image": image}]}})


def test_digest_pinned_image_has_no_git_sha():
    client = _one_service("527.dkr.ecr.eu-west-1.amazonaws.com/api@sha256:deadbeef")
    svc = ECSDeployRegistry(client, cluster="production").list_deployed_services()[0]
    assert svc.git_sha is None


def test_latest_tag_has_no_git_sha():
    client = _one_service("r/api:latest")
    svc = ECSDeployRegistry(client, cluster="production").list_deployed_services()[0]
    assert svc.git_sha is None


def test_one_failing_service_does_not_sink_others():
    services = [
        {
            "serviceArn": "a/good",
            "serviceName": "good",
            "runningCount": 1,
            "desiredCount": 1,
            "taskDefinition": "arn:td:good:1",
            "deployments": [
                {
                    "status": "PRIMARY",
                    "rolloutState": "COMPLETED",
                    "updatedAt": datetime(2026, 5, 29, tzinfo=UTC),
                    "taskDefinition": "arn:td:good:1",
                }
            ],
        },
        {
            "serviceArn": "a/bad",
            "serviceName": "bad",
            "runningCount": 1,
            "desiredCount": 1,
            "taskDefinition": "arn:td:bad:1",
            "deployments": [
                {
                    "status": "PRIMARY",
                    "rolloutState": "COMPLETED",
                    "updatedAt": datetime(2026, 5, 29, tzinfo=UTC),
                    "taskDefinition": "arn:td:bad:1",
                }
            ],
        },
    ]
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [{"serviceArns": ["a/good", "a/bad"]}]
    client.describe_services.return_value = {"services": services}

    def _td(taskDefinition):
        if taskDefinition == "arn:td:bad:1":
            raise RuntimeError("AccessDenied")
        return {"taskDefinition": {"containerDefinitions": [{"image": "r/good:goodsha"}]}}

    client.describe_task_definition.side_effect = _td
    rows = {
        s.name: s for s in ECSDeployRegistry(client, cluster="production").list_deployed_services()
    }
    assert rows["good"].git_sha == "goodsha"
    assert rows["bad"].git_sha is None
    assert rows["bad"].status.startswith("error")


def test_describe_failures_become_rows():
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [{"serviceArns": ["x"]}]
    client.describe_services.return_value = {
        "services": [],
        "failures": [
            {"arn": "arn:aws:ecs:eu-west-1:1:service/production/ghost", "reason": "MISSING"}
        ],
    }
    rows = ECSDeployRegistry(client, cluster="production").list_deployed_services()
    assert len(rows) == 1
    assert rows[0].name == "ghost"
    assert "MISSING" in rows[0].status

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from maki.rollout_status.service import RolloutStatusService

NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)


def _client(services=None, failures=None):
    client = MagicMock()
    client.describe_services.return_value = {
        "services": services or [],
        "failures": failures or [],
    }
    return client


def _service(client) -> RolloutStatusService:
    return RolloutStatusService(client, cluster="production", now=lambda: NOW)


def test_primary_in_progress_with_draining_active():
    primary_created = datetime(2026, 7, 8, 11, 55, tzinfo=UTC)
    active_created = datetime(2026, 7, 8, 11, 40, tzinfo=UTC)
    services = [
        {
            "serviceName": "newsfeed",
            "deployments": [
                {
                    "status": "PRIMARY",
                    "rolloutState": "IN_PROGRESS",
                    "rolloutStateReason": "ECS deployment ecs-svc/1 in progress.",
                    "desiredCount": 3,
                    "runningCount": 1,
                    "pendingCount": 2,
                    "failedTasks": 0,
                    "taskDefinition": "arn:td:newsfeed:6",
                    "createdAt": primary_created,
                    "updatedAt": primary_created,
                },
                {
                    "status": "ACTIVE",
                    "rolloutState": None,
                    "rolloutStateReason": None,
                    "desiredCount": 3,
                    "runningCount": 2,
                    "pendingCount": 0,
                    "failedTasks": 0,
                    "taskDefinition": "arn:td:newsfeed:5",
                    "createdAt": active_created,
                    "updatedAt": active_created,
                },
            ],
        }
    ]
    result = _service(_client(services)).get_rollout("newsfeed")
    assert result.service == "newsfeed"
    assert result.in_progress is True
    assert len(result.deployments) == 2
    primary, active = result.deployments
    assert primary.status == "PRIMARY"
    assert primary.rollout_state == "IN_PROGRESS"
    assert primary.running_count == 1
    assert primary.pending_count == 2
    assert primary.desired_count == 3
    assert active.status == "ACTIVE"
    assert active.running_count == 2


def test_single_primary_completed_has_no_active_deployment():
    services = [
        {
            "serviceName": "newsfeed",
            "deployments": [
                {
                    "status": "PRIMARY",
                    "rolloutState": "COMPLETED",
                    "rolloutStateReason": "ECS deployment ecs-svc/1 completed.",
                    "desiredCount": 3,
                    "runningCount": 3,
                    "pendingCount": 0,
                    "failedTasks": 0,
                    "taskDefinition": "arn:td:newsfeed:6",
                    "createdAt": NOW,
                    "updatedAt": NOW,
                }
            ],
        }
    ]
    result = _service(_client(services)).get_rollout("newsfeed")
    assert result.in_progress is False
    assert len(result.deployments) == 1
    assert result.deployments[0].rollout_state == "COMPLETED"


def test_unknown_service_raises_404():
    client = _client(services=[], failures=[{"arn": "arn:.../missing", "reason": "MISSING"}])
    with pytest.raises(HTTPException) as exc_info:
        _service(client).get_rollout("missing")
    assert exc_info.value.status_code == 404

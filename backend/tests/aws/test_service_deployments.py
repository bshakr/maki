from datetime import UTC, datetime
from unittest.mock import MagicMock

from maki.aws.service_deployments import ECSServiceDeployments

TD_REV7 = "arn:aws:ecs:eu-west-1:1:task-definition/newsfeed:7"


def _client(deployment_pages, revisions):
    # list_service_deployments has no botocore paginator; the code pages manually via
    # nextToken. Mock one response per page, chaining nextToken, last page tokenless.
    client = MagicMock()
    pages = deployment_pages or [[]]
    responses = []
    for i, page in enumerate(pages):
        resp: dict = {"serviceDeployments": page}
        if i < len(pages) - 1:
            resp["nextToken"] = f"tok{i + 1}"
        responses.append(resp)
    client.list_service_deployments.side_effect = responses
    client.describe_service_revisions.side_effect = lambda serviceRevisionArns: {
        "serviceRevisions": [revisions[a] for a in serviceRevisionArns if a in revisions]
    }
    return client


def test_state_by_revision_maps_finished_and_status():
    finished = datetime(2026, 5, 30, 10, 0, tzinfo=UTC)
    sr_success = "arn:aws:ecs:eu-west-1:1:service-revision/production/newsfeed/s"
    sr_progress = "arn:aws:ecs:eu-west-1:1:service-revision/production/newsfeed/p"
    sr_rollback = "arn:aws:ecs:eu-west-1:1:service-revision/production/newsfeed/r"
    sr_stopped = "arn:aws:ecs:eu-west-1:1:service-revision/production/newsfeed/x"
    td7 = "arn:aws:ecs:eu-west-1:1:task-definition/newsfeed:7"
    td8 = "arn:aws:ecs:eu-west-1:1:task-definition/newsfeed:8"
    td9 = "arn:aws:ecs:eu-west-1:1:task-definition/newsfeed:9"
    td10 = "arn:aws:ecs:eu-west-1:1:task-definition/newsfeed:10"
    pages = [
        [
            {
                "targetServiceRevisionArn": sr_success,
                "createdAt": datetime(2026, 5, 30, 9, 0, tzinfo=UTC),
                "finishedAt": finished,
                "status": "SUCCESSFUL",
            },
            {
                "targetServiceRevisionArn": sr_progress,
                "createdAt": datetime(2026, 5, 30, 9, 0, tzinfo=UTC),
                "finishedAt": None,  # in-progress: no finishedAt, but status still reported
                "status": "IN_PROGRESS",
            },
            {
                "targetServiceRevisionArn": sr_rollback,
                "createdAt": datetime(2026, 5, 30, 9, 0, tzinfo=UTC),
                "finishedAt": finished,
                "status": "ROLLBACK_SUCCESSFUL",
            },
            {
                "targetServiceRevisionArn": sr_stopped,
                "createdAt": datetime(2026, 5, 30, 9, 0, tzinfo=UTC),
                "finishedAt": None,
                "status": "STOPPED",
            },
        ]
    ]
    revisions = {
        sr_success: {"serviceRevisionArn": sr_success, "taskDefinition": td7},
        sr_progress: {"serviceRevisionArn": sr_progress, "taskDefinition": td8},
        sr_rollback: {"serviceRevisionArn": sr_rollback, "taskDefinition": td9},
        sr_stopped: {"serviceRevisionArn": sr_stopped, "taskDefinition": td10},
    }
    out = ECSServiceDeployments(_client(pages, revisions), "production").state_by_revision(
        "newsfeed", datetime(2026, 3, 1, tzinfo=UTC), "newsfeed"
    )
    assert out == {
        7: {"finished_at": finished, "status": "SUCCESSFUL"},
        8: {"finished_at": None, "status": "IN_PROGRESS"},
        9: {"finished_at": finished, "status": "ROLLBACK_SUCCESSFUL"},
        10: {"finished_at": None, "status": "STOPPED"},
    }


def test_state_by_revision_keeps_newest_brief_for_a_revision():
    # Two service-revision arns both map to task-def revision 7: a forward deploy then a later
    # rollback to the same image. The newest (rollback) brief must win.
    earlier = datetime(2026, 5, 30, 8, 0, tzinfo=UTC)
    later = datetime(2026, 5, 31, 9, 0, tzinfo=UTC)
    sr_a = "arn:aws:ecs:eu-west-1:1:service-revision/production/newsfeed/a"
    sr_b = "arn:aws:ecs:eu-west-1:1:service-revision/production/newsfeed/b"
    pages = [
        [
            {
                "targetServiceRevisionArn": sr_a,
                "createdAt": earlier,
                "finishedAt": earlier,
                "status": "SUCCESSFUL",
            },
            {
                "targetServiceRevisionArn": sr_b,
                "createdAt": later,
                "finishedAt": later,
                "status": "ROLLBACK_SUCCESSFUL",
            },
        ]
    ]
    revisions = {
        sr_a: {"serviceRevisionArn": sr_a, "taskDefinition": TD_REV7},
        sr_b: {"serviceRevisionArn": sr_b, "taskDefinition": TD_REV7},
    }
    out = ECSServiceDeployments(_client(pages, revisions), "production").state_by_revision(
        "newsfeed", datetime(2026, 3, 1, tzinfo=UTC), "newsfeed"
    )
    assert out == {7: {"finished_at": later, "status": "ROLLBACK_SUCCESSFUL"}}


def test_state_by_revision_failure_returns_empty_and_warns(caplog):
    client = MagicMock()
    client.list_service_deployments.side_effect = RuntimeError("UnsupportedFeatureException")
    with caplog.at_level("WARNING"):
        out = ECSServiceDeployments(client, "production").state_by_revision(
            "newsfeed", datetime(2026, 3, 1, tzinfo=UTC), "newsfeed"
        )
    assert out == {}  # never raises
    assert any("state_by_revision failed" in r.message for r in caplog.records)

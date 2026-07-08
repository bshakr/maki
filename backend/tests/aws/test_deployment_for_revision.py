from datetime import UTC, datetime
from unittest.mock import MagicMock

from maki.aws.service_deployments import ECSServiceDeployments

SR_REV7 = "arn:aws:ecs:eu-west-1:1:service-revision/production/newsfeed/aaa"
SR_REV6 = "arn:aws:ecs:eu-west-1:1:service-revision/production/newsfeed/bbb"
TD_REV7 = "arn:aws:ecs:eu-west-1:1:task-definition/newsfeed:7"
TD_REV6 = "arn:aws:ecs:eu-west-1:1:task-definition/newsfeed:6"


def _client(deployment_pages, revisions):
    # list_service_deployments has no botocore paginator; the code pages manually via
    # nextToken. Mock one response per page, chaining nextToken, last page tokenless.
    client = MagicMock()
    pages = deployment_pages or [[]]
    responses = []
    for i, page in enumerate(pages):
        resp = {"serviceDeployments": page}
        if i < len(pages) - 1:
            resp["nextToken"] = f"tok{i + 1}"
        responses.append(resp)
    client.list_service_deployments.side_effect = responses
    client.describe_service_revisions.side_effect = lambda serviceRevisionArns: {
        "serviceRevisions": [revisions[a] for a in serviceRevisionArns if a in revisions]
    }
    return client


def test_returns_timestamps_for_matching_revision():
    created = datetime(2026, 5, 29, 4, 0, tzinfo=UTC)
    started = datetime(2026, 5, 29, 4, 0, 12, tzinfo=UTC)
    finished = datetime(2026, 5, 29, 4, 3, 16, tzinfo=UTC)
    pages = [
        [
            {
                "targetServiceRevisionArn": SR_REV7,
                "createdAt": created,
                "startedAt": started,
                "finishedAt": finished,
                "status": "SUCCESSFUL",
            },
            {
                "targetServiceRevisionArn": SR_REV6,
                "createdAt": datetime(2026, 5, 28, tzinfo=UTC),
                "startedAt": datetime(2026, 5, 28, tzinfo=UTC),
                "finishedAt": datetime(2026, 5, 28, tzinfo=UTC),
                "status": "SUCCESSFUL",
            },
        ]
    ]
    revisions = {
        SR_REV7: {"serviceRevisionArn": SR_REV7, "taskDefinition": TD_REV7},
        SR_REV6: {"serviceRevisionArn": SR_REV6, "taskDefinition": TD_REV6},
    }
    out = ECSServiceDeployments(_client(pages, revisions), "production").deployment_for_revision(
        "newsfeed", 7, "newsfeed"
    )
    assert out == {
        "created_at": created,
        "started_at": started,
        "finished_at": finished,
        "status": "SUCCESSFUL",
    }


def test_returns_none_when_no_deployment_matches_revision():
    pages = [
        [
            {
                "targetServiceRevisionArn": SR_REV6,
                "createdAt": datetime(2026, 5, 28, tzinfo=UTC),
                "startedAt": datetime(2026, 5, 28, tzinfo=UTC),
                "finishedAt": datetime(2026, 5, 28, tzinfo=UTC),
                "status": "SUCCESSFUL",
            }
        ]
    ]
    revisions = {SR_REV6: {"serviceRevisionArn": SR_REV6, "taskDefinition": TD_REV6}}
    out = ECSServiceDeployments(_client(pages, revisions), "production").deployment_for_revision(
        "newsfeed", 7, "newsfeed"
    )
    assert out is None


def test_returns_none_when_no_deployments_at_all():
    client = _client([[]], {})
    out = ECSServiceDeployments(client, "production").deployment_for_revision(
        "newsfeed", 7, "newsfeed"
    )
    assert out is None
    client.describe_service_revisions.assert_not_called()


def test_picks_newest_deployment_when_revision_reships():
    older = datetime(2026, 5, 20, tzinfo=UTC)
    newer = datetime(2026, 5, 29, tzinfo=UTC)
    sr_a = "arn:aws:ecs:eu-west-1:1:service-revision/production/newsfeed/a"
    sr_b = "arn:aws:ecs:eu-west-1:1:service-revision/production/newsfeed/b"
    pages = [
        [
            {"targetServiceRevisionArn": sr_a, "createdAt": older, "status": "SUCCESSFUL"},
            {"targetServiceRevisionArn": sr_b, "createdAt": newer, "status": "SUCCESSFUL"},
        ]
    ]
    revisions = {
        sr_a: {"serviceRevisionArn": sr_a, "taskDefinition": TD_REV7},
        sr_b: {"serviceRevisionArn": sr_b, "taskDefinition": TD_REV7},
    }
    out = ECSServiceDeployments(_client(pages, revisions), "production").deployment_for_revision(
        "newsfeed", 7, "newsfeed"
    )
    assert out["created_at"] == newer


def test_list_failure_returns_none_and_warns(caplog):
    client = MagicMock()
    client.list_service_deployments.side_effect = RuntimeError("Unsupported")
    with caplog.at_level("WARNING"):
        out = ECSServiceDeployments(client, "production").deployment_for_revision(
            "newsfeed", 7, "newsfeed"
        )
    assert out is None
    assert any("deployment_for_revision failed" in r.message for r in caplog.records)


def test_describe_failure_returns_none_and_warns(caplog):
    brief = {"targetServiceRevisionArn": SR_REV7, "createdAt": datetime(2026, 5, 29, tzinfo=UTC)}
    pages = [[brief]]
    client = _client(pages, {})
    client.describe_service_revisions.side_effect = RuntimeError("AccessDenied")
    with caplog.at_level("WARNING"):
        out = ECSServiceDeployments(client, "production").deployment_for_revision(
            "newsfeed", 7, "newsfeed"
        )
    assert out is None
    assert any("deployment_for_revision failed" in r.message for r in caplog.records)


def test_family_mismatch_excluded():
    brief = {"targetServiceRevisionArn": SR_REV7, "createdAt": datetime(2026, 5, 29, tzinfo=UTC)}
    pages = [[brief]]
    # describe maps the arn to a DIFFERENT family at the same revision number
    other_td = "arn:aws:ecs:eu-west-1:1:task-definition/other-svc:7"
    revisions = {SR_REV7: {"serviceRevisionArn": SR_REV7, "taskDefinition": other_td}}
    out = ECSServiceDeployments(_client(pages, revisions), "production").deployment_for_revision(
        "newsfeed", 7, "newsfeed"
    )
    assert out is None

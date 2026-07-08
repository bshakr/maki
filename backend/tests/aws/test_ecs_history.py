from datetime import UTC, datetime
from unittest.mock import MagicMock

from maki.aws.ecs_history import ECSDeployHistory


def _client(arns_by_page, task_defs):
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [
        {"taskDefinitionArns": page} for page in arns_by_page
    ]
    client.describe_task_definition.side_effect = lambda taskDefinition: {
        "taskDefinition": task_defs[taskDefinition]
    }
    return client


def test_lists_revisions_newest_first_with_sha_and_revision():
    t2 = datetime(2026, 5, 30, 10, 0, tzinfo=UTC)
    t1 = datetime(2026, 5, 29, 10, 0, tzinfo=UTC)
    arn2 = "arn:aws:ecs:eu-west-1:1:task-definition/newsfeed:2"
    arn1 = "arn:aws:ecs:eu-west-1:1:task-definition/newsfeed:1"
    task_defs = {
        arn2: {"registeredAt": t2, "containerDefinitions": [{"image": "r/newsfeed:shaB"}]},
        arn1: {"registeredAt": t1, "containerDefinitions": [{"image": "r/newsfeed:shaA"}]},
    }
    history = ECSDeployHistory(_client([[arn2, arn1]], task_defs))
    deploys = history.list_deploys("newsfeed")
    assert [d.sha for d in deploys] == ["shaB", "shaA"]
    assert deploys[0].revision == 2
    assert deploys[0].registered_at == t2
    assert deploys[1].revision == 1


def test_respects_limit():
    arns = [f"arn:aws:ecs:eu-west-1:1:task-definition/svc:{i}" for i in range(50, 0, -1)]
    task_defs = {
        a: {"registeredAt": None, "containerDefinitions": [{"image": "r/svc:s"}]} for a in arns
    }
    history = ECSDeployHistory(_client([arns], task_defs))
    deploys = history.list_deploys("svc", limit=5)
    assert len(deploys) == 5


def test_describe_task_definition_cached_per_arn_forever():
    arn = "arn:aws:ecs:eu-west-1:1:task-definition/newsfeed:1"
    task_defs = {arn: {"registeredAt": None, "containerDefinitions": [{"image": "r/newsfeed:s"}]}}
    client = _client([[arn]], task_defs)
    history = ECSDeployHistory(client)
    history.list_deploys("newsfeed")
    history.list_deploys("newsfeed")  # re-list same family
    # immutable revision described exactly once across both calls
    assert client.describe_task_definition.call_count == 1


def _window_client(arns_in_order, registered_by_arn):
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [
        {"taskDefinitionArns": arns_in_order}
    ]
    client.describe_task_definition.side_effect = lambda taskDefinition: {
        "taskDefinition": {
            "registeredAt": registered_by_arn[taskDefinition],
            "containerDefinitions": [{"image": "r/svc:s"}],
        }
    }
    return client


def test_since_keeps_in_window_and_stops_early_at_first_older_revision():
    # Revisions newest->oldest: 3 in-window, then older ones that must never be described.
    since = datetime(2026, 5, 25, 0, 0, tzinfo=UTC)
    arns = [f"arn:aws:ecs:eu-west-1:1:task-definition/svc:{i}" for i in (5, 4, 3, 2, 1)]
    registered = {
        arns[0]: datetime(2026, 5, 30, tzinfo=UTC),  # in
        arns[1]: datetime(2026, 5, 28, tzinfo=UTC),  # in
        arns[2]: datetime(2026, 5, 26, tzinfo=UTC),  # in
        arns[3]: datetime(2026, 5, 20, tzinfo=UTC),  # out -> triggers break
        arns[4]: datetime(2026, 5, 10, tzinfo=UTC),  # never reached
    }
    client = _window_client(arns, registered)
    history = ECSDeployHistory(client)
    deploys = history.list_deploys("svc", since=since)

    assert [d.revision for d in deploys] == [5, 4, 3]
    # Early stop: described the 3 in-window + the first out-of-window one, then broke.
    assert client.describe_task_definition.call_count == 4


def test_since_max_revisions_caps_and_warns(caplog):
    since = datetime(2026, 5, 1, tzinfo=UTC)
    arns = [f"arn:aws:ecs:eu-west-1:1:task-definition/svc:{i}" for i in range(10, 0, -1)]
    registered = {a: datetime(2026, 5, 20, tzinfo=UTC) for a in arns}  # all in-window
    client = _window_client(arns, registered)
    history = ECSDeployHistory(client)
    with caplog.at_level("WARNING"):
        deploys = history.list_deploys("svc", since=since, max_revisions=4)
    assert len(deploys) == 4
    assert any("max_revisions" in r.message for r in caplog.records)


def test_since_none_unchanged_uses_count_cap():
    arns = [f"arn:aws:ecs:eu-west-1:1:task-definition/svc:{i}" for i in range(50, 0, -1)]
    task_defs = {
        a: {"registeredAt": None, "containerDefinitions": [{"image": "r/svc:s"}]} for a in arns
    }
    history = ECSDeployHistory(_client([arns], task_defs))
    deploys = history.list_deploys("svc", limit=5, since=None)
    assert len(deploys) == 5


def test_family_from_arn():
    assert (
        ECSDeployHistory.family_from_arn("arn:aws:ecs:eu-west-1:1:task-definition/wfm-service:42")
        == "wfm-service"
    )
    assert ECSDeployHistory.family_from_arn("nonsense") is None

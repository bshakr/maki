from unittest.mock import MagicMock

from maki.aws.logs import LogTailResult
from maki.logs.service import ServiceLogsService


def _service(*, resolved, tail_result=None):
    tail = MagicMock()
    tail.tail.return_value = tail_result or LogTailResult(events=[], truncated=False)
    task_def = MagicMock()
    task_def.log_group.return_value = resolved
    svc = ServiceLogsService(
        tail=tail,
        task_def=task_def,
        region="eu-west-1",
        fresh_seconds=0.0,
        stale_seconds=0.0,
    )
    return svc, tail, task_def


def test_uses_resolved_group_and_region_for_tail_and_response():
    svc, tail, _ = _service(resolved=("/ecs/inventory-real", "eu-west-2"))
    resp = svc.get_logs("inventory", limit=10, since_minutes=30)

    # The resolved group drives the tail call AND the response.
    tail.tail.assert_called_once_with("/ecs/inventory-real", limit=10, since_minutes=30)
    assert resp.log_group == "/ecs/inventory-real"
    assert resp.region == "eu-west-2"


def test_falls_back_to_configured_region_when_task_def_has_no_region():
    svc, _, _ = _service(resolved=("/ecs/inventory-real", None))
    resp = svc.get_logs("inventory", limit=10, since_minutes=30)

    assert resp.log_group == "/ecs/inventory-real"
    assert resp.region == "eu-west-1"


def test_falls_back_to_convention_when_resolution_returns_none():
    svc, tail, _ = _service(resolved=None)
    resp = svc.get_logs("inventory", limit=10, since_minutes=30)

    tail.tail.assert_called_once_with("/ecs/inventory-production", limit=10, since_minutes=30)
    assert resp.log_group == "/ecs/inventory-production"
    assert resp.region == "eu-west-1"


def test_preserves_typed_error_from_tail():
    svc, _, _ = _service(
        resolved=("/ecs/inventory-real", None),
        tail_result=LogTailResult(events=[], error="not_found"),
    )
    resp = svc.get_logs("inventory", limit=10, since_minutes=30)

    assert resp.error == "not_found"
    # Even on a not_found tail, the resolved group is what we report.
    assert resp.log_group == "/ecs/inventory-real"

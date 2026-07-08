from datetime import UTC, datetime
from unittest.mock import MagicMock

from maki.task_history.service import TaskHistoryService, _period_for

NOW = datetime(2026, 5, 31, 12, 0, tzinfo=UTC)
T0 = datetime(2026, 5, 30, 10, 0, tzinfo=UTC)
T1 = datetime(2026, 5, 30, 11, 0, tzinfo=UTC)


def _metrics(points):
    m = MagicMock()
    m.task_history.return_value = points
    return m


def _service(metrics, fresh=0.0, stale=0.0):
    return TaskHistoryService(
        metrics=metrics, fresh_seconds=fresh, stale_seconds=stale, now=lambda: NOW
    )


def test_period_for_mapping():
    assert _period_for(1) == 3600  # 1-hour buckets keep short ranges readable, not a barcode
    assert _period_for(7) == 3600
    assert _period_for(30) == 3600
    assert _period_for(90) == 21600
    assert _period_for(31) == 21600


def test_maps_points_and_rounds_floats_to_int():
    metrics = _metrics(
        [
            {"timestamp": T0, "running": 2.0, "desired": 3.0},
            {"timestamp": T1, "running": 2.6, "desired": None},
        ]
    )
    resp = _service(metrics).get_task_history("inventory", 30)

    assert resp.service == "inventory"
    assert resp.range_days == 30
    assert resp.period_seconds == 3600
    assert resp.generated_at == NOW
    assert [(p.running, p.desired) for p in resp.points] == [(2, 3), (3, None)]


def test_computes_window_and_period_passed_to_metrics():
    metrics = _metrics([])
    _service(metrics).get_task_history("inventory", 7)

    args, kwargs = metrics.task_history.call_args
    service_name, start, end, period = args
    assert service_name == "inventory"
    assert end == NOW
    assert (end - start).days == 7
    assert period == 3600  # 1-hour buckets


def test_fail_soft_metrics_empty_still_valid_response():
    # CloudWatch wrapper already returns [] on error; the service must still build a response.
    resp = _service(_metrics([])).get_task_history("inventory", 90)
    assert resp.points == []
    assert resp.period_seconds == 21600
    assert resp.service == "inventory"


def test_swr_cache_reuse_within_fresh_window():
    metrics = _metrics([{"timestamp": T0, "running": 1.0, "desired": 1.0}])
    svc = _service(metrics, fresh=300.0, stale=600.0)

    svc.get_task_history("inventory", 30)
    svc.get_task_history("inventory", 30)
    assert metrics.task_history.call_count == 1  # second call served from cache

    svc.get_task_history("inventory", 30, force=True)
    assert metrics.task_history.call_count == 2  # force bypasses the cache

    svc.get_task_history("workforce", 30)
    assert metrics.task_history.call_count == 3  # different key recomputes

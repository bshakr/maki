from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from maki.aws.cloudwatch import CloudWatchTaskMetrics
from maki.cache import SwrCache
from maki.schemas import TaskHistoryPoint, TaskHistoryResponse


def _period_for(range_days: int) -> int:
    """CloudWatch ``Period`` (seconds) sized to the range.

    1-hour buckets keep the chart readable (a 5-min period over a week is ~2000 noisy points that
    render as a barcode); 6-hour for long ranges. Well within CloudWatch retention (1-hour data
    lives 455 days). <=30d → 3600 (1-hour), else → 21600 (6-hour).
    """
    if range_days <= 30:
        return 3600
    return 21600


def _to_int(value: float | None) -> int | None:
    """Task counts are whole numbers; round CloudWatch floats to int, keep None when absent."""
    return None if value is None else round(value)


class TaskHistoryService:
    """Running-vs-desired task history for one service, SWR-cached over CloudWatch reads."""

    def __init__(
        self,
        metrics: CloudWatchTaskMetrics,
        fresh_seconds: float,
        stale_seconds: float,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._metrics = metrics
        self._now = now
        self._cache = SwrCache(fresh_seconds, stale_seconds)

    def get_task_history(
        self, service_name: str, range_days: int, force: bool = False
    ) -> TaskHistoryResponse:
        return self._cache.get(
            (service_name, range_days),
            lambda: self._compute(service_name, range_days),
            force=force,
        )

    def _compute(self, service_name: str, range_days: int) -> TaskHistoryResponse:
        now = self._now()
        start = now - timedelta(days=range_days)
        period = _period_for(range_days)
        raw = self._metrics.task_history(service_name, start, now, period)
        points = [
            TaskHistoryPoint(
                timestamp=point["timestamp"],
                running=_to_int(point.get("running")),
                desired=_to_int(point.get("desired")),
            )
            for point in raw
        ]
        return TaskHistoryResponse(
            service=service_name,
            range_days=range_days,
            period_seconds=period,
            points=points,
            generated_at=now,
        )

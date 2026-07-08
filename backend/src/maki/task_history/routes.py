from functools import cache

from fastapi import APIRouter, Query

from maki.aws.clients import cloudwatch_client
from maki.aws.cloudwatch import CloudWatchTaskMetrics
from maki.schemas import TaskHistoryResponse
from maki.settings import settings
from maki.task_history.service import TaskHistoryService

router = APIRouter(prefix="/api")


@cache
def get_task_history_service() -> TaskHistoryService:
    return TaskHistoryService(
        metrics=CloudWatchTaskMetrics(cloudwatch_client(), settings.ecs_cluster),
        fresh_seconds=settings.swr_fresh_seconds,
        stale_seconds=settings.swr_stale_seconds,
    )


@router.get("/services/{name}/task-history", response_model=TaskHistoryResponse)
def get_task_history(
    name: str,
    # Bounded so a nonsense range isn't a silently-empty chart: <1 inverts start/end (CloudWatch
    # rejects it) and >455d is past CloudWatch's longest (1h/6h) retention.
    range_days: int = Query(default=30, ge=1, le=455),
    refresh: bool = False,
) -> TaskHistoryResponse:
    return get_task_history_service().get_task_history(name, range_days, force=refresh)

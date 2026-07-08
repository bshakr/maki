from functools import cache

from fastapi import APIRouter, Query

from maki.aws.clients import ecs_client, logs_client
from maki.aws.logs import LogTail
from maki.aws.task_definition import ECSTaskDefinition
from maki.logs.service import ServiceLogsService
from maki.schemas import ServiceLogsResponse
from maki.settings import settings

router = APIRouter(prefix="/api")

# Short cache: the viewer should feel live (and auto-refresh polls ~5s), but a burst of refreshes
# shouldn't fan out one FilterLogEvents call each. A manual ?refresh=1 always bypasses it.
_LOGS_FRESH_SECONDS = 3.0
_LOGS_STALE_SECONDS = 30.0


@cache
def get_logs_service() -> ServiceLogsService:
    return ServiceLogsService(
        tail=LogTail(logs_client()),
        task_def=ECSTaskDefinition(ecs_client(), settings.ecs_cluster),
        region=settings.aws_region,
        fresh_seconds=_LOGS_FRESH_SECONDS,
        stale_seconds=_LOGS_STALE_SECONDS,
    )


@router.get("/services/{name}/logs", response_model=ServiceLogsResponse)
def get_service_logs(
    name: str,
    # Bounded: a tail viewer needs a manageable slice, not the whole group. <=1000 keeps the
    # response light; the window is capped at 24h since older events are for the console.
    limit: int = Query(default=200, ge=1, le=1000),
    since_minutes: int = Query(default=60, ge=1, le=1440),
    refresh: bool = False,
) -> ServiceLogsResponse:
    return get_logs_service().get_logs(name, limit, since_minutes, force=refresh)

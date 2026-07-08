from functools import cache
from typing import Annotated

from fastapi import APIRouter, Query

from maki.db.engine import get_session
from maki.db.repository import DeployEventRepository
from maki.history.service import HistoryService
from maki.inventory.routes import get_inventory_service
from maki.metrics.service import MetricsService
from maki.schemas import MetricsResponse
from maki.settings import settings

router = APIRouter(prefix="/api")


@cache
def get_metrics_service() -> MetricsService:
    history = HistoryService(
        repository=DeployEventRepository(),
        session_factory=get_session,
        fresh_seconds=settings.swr_fresh_seconds,
        stale_seconds=settings.swr_stale_seconds,
    )
    return MetricsService(
        inventory=get_inventory_service(),
        history=history,
        fresh_seconds=settings.swr_fresh_seconds,
        stale_seconds=settings.swr_stale_seconds,
    )


@router.get("/metrics", response_model=MetricsResponse)
def get_metrics(
    range_days: Annotated[int, Query(ge=1, le=365)] = 30,
    service: str = "all",
    refresh: bool = False,
) -> MetricsResponse:
    return get_metrics_service().get_metrics(range_days, service, force=refresh)

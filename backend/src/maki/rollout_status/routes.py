from functools import cache

from fastapi import APIRouter

from maki.aws.clients import ecs_client
from maki.rollout_status.service import RolloutStatusService
from maki.schemas import RolloutStatusResponse
from maki.settings import settings

router = APIRouter(prefix="/api")


@cache
def get_rollout_status_service() -> RolloutStatusService:
    # No SwrCache here, unlike every other domain: this endpoint exists to be polled at 3-5s
    # while a rollout is in progress, and a fresh-window cache would defeat that entirely. One
    # describe_services call for one service per request is cheap.
    return RolloutStatusService(ecs_client(), cluster=settings.ecs_cluster)


@router.get("/services/{name}/rollout", response_model=RolloutStatusResponse)
def get_service_rollout(name: str) -> RolloutStatusResponse:
    return get_rollout_status_service().get_rollout(name)

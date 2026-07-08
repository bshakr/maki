from functools import cache

from fastapi import APIRouter

from maki.aws.clients import ecs_client
from maki.aws.task_definition import ECSTaskDefinition
from maki.schemas import ServiceEnvResponse
from maki.service_env.service import ServiceEnvService
from maki.settings import settings

router = APIRouter(prefix="/api")


@cache
def get_service_env_service() -> ServiceEnvService:
    # No SWR window: env values can be plaintext secrets, so the service never caches them.
    return ServiceEnvService(task_def=ECSTaskDefinition(ecs_client(), settings.ecs_cluster))


@router.get("/services/{name}/env", response_model=ServiceEnvResponse)
def get_service_env(name: str) -> ServiceEnvResponse:
    return get_service_env_service().get_env(name)

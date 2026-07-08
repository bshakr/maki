from functools import cache

from fastapi import APIRouter

from maki.aws.amplify_registry import AmplifyDeployRegistry
from maki.aws.clients import amplify_client, ecs_client
from maki.aws.ecs_registry import ECSDeployRegistry
from maki.github_enrich import GitHubEnricher
from maki.inventory.service import InventoryService
from maki.schemas import ServicesResponse
from maki.settings import settings

router = APIRouter(prefix="/api")


@cache
def get_inventory_service() -> InventoryService:
    # Amplify is optional: skip it (no web-app row, no client call) when disabled or when no app id
    # is configured — matching the pre-config behaviour rather than erroring per cycle.
    amplify: AmplifyDeployRegistry | None = None
    app_id = settings.amplify_app_id
    if settings.amplify_enabled and app_id:
        amplify = AmplifyDeployRegistry(
            amplify_client(),
            app_id=app_id,
            branch=settings.amplify_branch,
            service_name=settings.amplify_service_name,
        )
    return InventoryService(
        ecs=ECSDeployRegistry(
            ecs_client(), cluster=settings.ecs_cluster, region=settings.aws_region
        ),
        amplify=amplify,
        enricher=GitHubEnricher(token=settings.github_token, base_url=settings.github_api_url),
        repo_for=settings.repo_for,
        fresh_seconds=settings.swr_fresh_seconds,
        stale_seconds=settings.swr_stale_seconds,
    )


@router.get("/services", response_model=ServicesResponse)
def list_services(refresh: bool = False) -> ServicesResponse:
    return get_inventory_service().get_inventory(force=refresh)

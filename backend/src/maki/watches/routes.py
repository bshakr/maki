from functools import cache

from fastapi import APIRouter
from pydantic import BaseModel

from maki.db.engine import get_session
from maki.db.repository import DeployEventRepository, ServiceWatchRepository
from maki.schemas import WatchedService, WatchesResponse
from maki.watches.service import WatchesService

router = APIRouter(prefix="/api")


class WatchRequest(BaseModel):
    service: str


@cache
def get_watches_service() -> WatchesService:
    return WatchesService(
        watches=ServiceWatchRepository(),
        deploys=DeployEventRepository(),
        session_factory=get_session,
    )


@router.get("/watches", response_model=WatchesResponse)
def list_watches() -> WatchesResponse:
    return get_watches_service().list()


@router.post("/watches", response_model=WatchedService, status_code=201)
def add_watch(body: WatchRequest) -> WatchedService:
    return get_watches_service().add(body.service)


@router.delete("/watches/{service}", status_code=204)
def remove_watch(service: str) -> None:
    get_watches_service().remove(service)

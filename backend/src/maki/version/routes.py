from functools import cache

from fastapi import APIRouter

from maki.schemas import VersionResponse
from maki.version.service import VersionService

router = APIRouter(prefix="/api")

# A fresh result lives an hour: long dev sessions re-hit the remote hourly at most, and the
# stale bound matches so a past-hour read blocks and re-checks rather than serving stale.
RECHECK_SECONDS = 3600.0


@cache
def get_version_service() -> VersionService:
    return VersionService(fresh_seconds=RECHECK_SECONDS, stale_seconds=RECHECK_SECONDS)


@router.get("/version", response_model=VersionResponse)
def get_version() -> VersionResponse:
    return get_version_service().get_version()

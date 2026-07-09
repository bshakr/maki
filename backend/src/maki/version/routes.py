import time

from fastapi import APIRouter

from maki.schemas import VersionResponse
from maki.version.service import check_version

router = APIRouter(prefix="/api")

RECHECK_SECONDS = 3600.0

# (checked_at monotonic, result). Long-running dev sessions re-hit the remote hourly at most;
# the SPA can poll freely without generating network calls.
_cached: tuple[float, VersionResponse] | None = None


@router.get("/version", response_model=VersionResponse)
def get_version() -> VersionResponse:
    global _cached
    now = time.monotonic()
    if _cached is None or now - _cached[0] > RECHECK_SECONDS:
        _cached = (now, check_version())
    return _cached[1]

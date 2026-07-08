from datetime import UTC, datetime
from functools import cache
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from maki.activity.cursor import InvalidCursor, decode_cursor
from maki.activity.service import ActivityService
from maki.db.engine import get_session
from maki.db.repository import DeployEventRepository
from maki.schemas import ActivityResponse, DeployCountResponse
from maki.settings import settings

router = APIRouter(prefix="/api")

_AROUND_DESC = (
    "ISO-8601 timestamp to centre the feed on (incident triage). When set, returns events "
    "within ±`window` hours of this moment instead of the latest feed."
)
_WINDOW_DESC = (
    "Half-width of the time window in hours (only used with `around`). Max 168 (1 week)."
)
_CURSOR_DESC = (
    "Opaque keyset cursor from a previous response's `next_cursor`. When set, returns the next "
    "(older) page of the default feed. Ignored when `around` is supplied."
)
_SINCE_DESC = "Count ECS deploy events registered at/after this ISO-8601 instant."


@cache
def get_activity_service() -> ActivityService:
    return ActivityService(
        repository=DeployEventRepository(),
        session_factory=get_session,
        fresh_seconds=settings.swr_fresh_seconds,
        stale_seconds=settings.swr_stale_seconds,
    )


@router.get("/activity", response_model=ActivityResponse)
def get_activity(
    refresh: bool = False,
    around: Annotated[datetime | None, Query(description=_AROUND_DESC)] = None,
    window: Annotated[float, Query(gt=0, le=168, description=_WINDOW_DESC)] = 6.0,
    cursor: Annotated[str | None, Query(description=_CURSOR_DESC)] = None,
) -> ActivityResponse:
    """Fleet-wide deploy feed.

    Default (no params): the latest cached feed's first page, newest first, with a ``next_cursor``
    for the next (older) page when more exist.
    With ``cursor``: the next keyset page of the default feed (read fresh, not from cache).
    With ``around``: every event whose go-live time falls within ±``window`` hours of the target,
    newest first — bounded by an explicit, larger cap, not paginated.
    """
    service = get_activity_service()
    if around is not None:
        return service.get_activity_around(around, window_hours=window)
    decoded: tuple[datetime, int] | None = None
    if cursor is not None:
        try:
            decoded = decode_cursor(cursor)
        except InvalidCursor as exc:
            raise HTTPException(status_code=422, detail="Invalid cursor") from exc
    return service.get_activity_page(cursor=decoded, force=refresh)


@router.get("/activity/deploy-count", response_model=DeployCountResponse)
def get_deploy_count(
    since: Annotated[datetime, Query(description=_SINCE_DESC)],
) -> DeployCountResponse:
    """Fleet-wide count of ECS deploy events registered at/after ``since``."""
    with get_session() as session:
        count = DeployEventRepository().count_registered_since(session, since)
    return DeployCountResponse(count=count, since=since, generated_at=datetime.now(UTC))

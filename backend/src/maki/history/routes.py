from datetime import datetime
from functools import cache
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from maki.activity.cursor import InvalidCursor, decode_cursor
from maki.db.engine import get_session
from maki.db.repository import DeployEventRepository
from maki.history.service import HistoryService
from maki.schemas import DeploymentsResponse, DeployRecord
from maki.settings import settings

router = APIRouter(prefix="/api")

_CURSOR_DESC = (
    "Opaque keyset cursor from a previous response's `next_cursor`. When set, returns the next "
    "(older) page of this service's history."
)


@cache
def get_history_service() -> HistoryService:
    return HistoryService(
        repository=DeployEventRepository(),
        session_factory=get_session,
        fresh_seconds=settings.swr_fresh_seconds,
        stale_seconds=settings.swr_stale_seconds,
    )


@router.get("/services/{name}/deployments", response_model=DeploymentsResponse)
def list_deployments(
    name: str,
    refresh: bool = False,
    cursor: Annotated[str | None, Query(description=_CURSOR_DESC)] = None,
) -> DeploymentsResponse:
    """One service's deploy history, newest first.

    Default (no cursor): the latest cached first page, with a ``next_cursor`` for the next (older)
    page when more exist. With ``cursor``: the next keyset page (read fresh, not from cache).
    """
    decoded: tuple[datetime, int] | None = None
    if cursor is not None:
        try:
            decoded = decode_cursor(cursor)
        except InvalidCursor as exc:
            raise HTTPException(status_code=422, detail="Invalid cursor") from exc
    return get_history_service().get_deployments_page(name, cursor=decoded, force=refresh)


@router.get("/services/{name}/deploys/{sha}", response_model=DeployRecord)
def get_deploy(name: str, sha: str) -> DeployRecord:
    """A single deploy for a service, matched by short-sha prefix.

    Backs the deploy-sheet deep link (e.g. from the metrics leaderboards) for shas that aren't in
    the loaded history page. Returns the matching ``DeployRecord``, or ``404`` when no stored deploy
    for the service matches the sha.
    """
    record = get_history_service().get_deploy(name, sha)
    if record is None:
        raise HTTPException(status_code=404, detail="Deploy not found")
    return record

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from maki.activity.cursor import encode_cursor
from maki.cache import SwrCache
from maki.db.engine import get_session
from maki.db.models import DeployEvent
from maki.db.repository import DeployEventRepository
from maki.schemas import ActivityItem, ActivityResponse


class ActivityService:
    """Fleet-wide chronological deploy feed read from the deploy-events store.

    A stream of the most-recent events across the fleet (multiple per service allowed), newest
    first. The store is already enriched by the ingester, so no live AWS fan-out is needed.
    """

    def __init__(
        self,
        repository: DeployEventRepository,
        fresh_seconds: float,
        stale_seconds: float,
        session_factory: Callable[[], AbstractContextManager[Session]] = get_session,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        limit: int = 50,
        max_window_events: int = 500,
    ):
        self._repository = repository
        self._session_factory = session_factory
        self._now = now
        self._limit = limit
        # Explicit, documented cap for time-window queries — far larger than the default feed's
        # ``limit`` so a "jump to timestamp" over a busy period isn't silently truncated to 50.
        self._max_window_events = max_window_events
        self._cache = SwrCache(fresh_seconds, stale_seconds)

    def get_activity(self, force: bool = False) -> ActivityResponse:
        return self._cache.get("activity", self._compute, force=force)

    def get_activity_page(
        self, cursor: tuple[datetime, int] | None = None, force: bool = False
    ) -> ActivityResponse:
        """Return one keyset page of the fleet-wide feed, newest go-live first.

        The first page (``cursor=None``) is served through the SWR cache, exactly like
        ``get_activity``. Subsequent pages (``cursor`` set) read the store fresh and bypass the
        cache — mirroring ``get_activity_around`` — so arbitrary cursors never pollute the
        latest-feed cache entry.

        The response's ``next_cursor`` is the keyset position of the last row when a full page was
        returned (so there may be more), and ``None`` once a short page signals the end.
        """
        if cursor is None:
            return self.get_activity(force=force)
        with self._session_factory() as session:
            return self._build_page(session, cursor)

    def _build_page(
        self, session: Session, cursor: tuple[datetime, int] | None
    ) -> ActivityResponse:
        events = self._repository.list_page(session, self._limit, before=cursor)
        items = [self._to_item(event) for event in events]
        # A full page means there may be more; encode the last row's keyset position. A short page
        # is the tail of the feed -> no next cursor.
        next_cursor = (
            encode_cursor(events[-1].finished_at or events[-1].registered_at, events[-1].id)
            if len(events) == self._limit and events
            else None
        )
        return ActivityResponse(items=items, generated_at=self._now(), next_cursor=next_cursor)

    def get_activity_around(self, around: datetime, window_hours: float) -> ActivityResponse:
        """Return events whose go-live time falls within ``window_hours`` either side of ``around``.

        Not cached: this is a parameterised point-in-time query (incident triage), so it always
        reads the store fresh rather than sharing the latest-feed cache entry.
        """
        window = timedelta(hours=window_hours)
        with self._session_factory() as session:
            events = self._repository.list_around(
                session, around, window, self._max_window_events
            )
            items = [self._to_item(event) for event in events]
        return ActivityResponse(items=items, generated_at=self._now())

    def _compute(self) -> ActivityResponse:
        with self._session_factory() as session:
            return self._build_page(session, cursor=None)

    @staticmethod
    def _to_item(event: DeployEvent) -> ActivityItem:
        # deployed_at = the go-live moment (finished_at), falling back to registered_at when the
        # rollout time is unknown (older than ECS retention). Consistent with the time-to-prod
        # fix: finished_at is the accurate live time, registered_at the build/registration time.
        return ActivityItem(
            id=event.id,
            service=event.service,
            platform=event.platform,
            sha=event.sha,
            deployed_at=event.finished_at or event.registered_at,
            status=event.status,
            is_rollback=event.is_rollback,
            author=event.author,
            author_avatar_url=event.author_avatar_url,
            message=event.message,
            commit_url=event.commit_url,
            pr_url=event.pr_url,
            committed_at=event.committed_at,
        )

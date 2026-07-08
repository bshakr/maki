from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from maki.activity.cursor import encode_cursor
from maki.cache import SwrCache
from maki.db.engine import get_session
from maki.db.models import DeployEvent
from maki.db.repository import DeployEventRepository
from maki.schemas import DeploymentsResponse, DeployRecord


class HistoryService:
    """Deploy history for one service, read from the deploy-events store.

    The background ingester already enriched each event with GitHub commit metadata and resolved
    ``finished_at``; reads simply map stored rows to ``DeployRecord``s. No live AWS fan-out.
    """

    def __init__(
        self,
        repository: DeployEventRepository,
        fresh_seconds: float,
        stale_seconds: float,
        session_factory: Callable[[], AbstractContextManager[Session]] = get_session,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        limit: int = 30,
    ):
        self._repository = repository
        self._session_factory = session_factory
        self._now = now
        self._limit = limit
        self._cache = SwrCache(fresh_seconds, stale_seconds)

    def get_deployments(self, service_name: str, force: bool = False) -> DeploymentsResponse:
        return self._cache.get(service_name, lambda: self._compute(service_name), force=force)

    def get_deployments_page(
        self, service_name: str, cursor: tuple[datetime, int] | None = None, force: bool = False
    ) -> DeploymentsResponse:
        """Return one keyset page of a service's history, newest registered first.

        The first page (``cursor=None``) is served through the SWR cache, exactly like
        ``get_deployments``. Subsequent pages (``cursor`` set) read the store fresh and bypass the
        cache, so arbitrary cursors never pollute the first-page cache entry. Mirrors
        ``ActivityService.get_activity_page``.

        The response's ``next_cursor`` is the keyset position of the last row when a full page was
        returned (so there may be more), and ``None`` once a short page signals the end.
        """
        if cursor is None:
            return self.get_deployments(service_name, force=force)
        with self._session_factory() as session:
            return self._compute_page(session, service_name, cursor)

    def get_deployments_since(
        self, service_name: str, since: datetime, force: bool = False
    ) -> list[DeployRecord]:
        """Enriched deploy records registered at/after ``since`` (for metrics' date window).

        Cached under a cutoff-DATE bucket so repeated calls within the same day/window share an
        entry, even when ``since`` timestamps differ by minutes. Unlike ``get_deployments`` (the
        service-detail card's newest-30 view), this returns every in-window event.

        No revision cap here (the old live fan-out capped at metrics_max_revisions_per_service,
        which under-counted busy services). The store is bounded by ingest retention and metrics
        need every in-window event for accurate counts, so the query is intentionally uncapped.
        """
        key = ("since", service_name, since.date().isoformat())
        return self._cache.get(key, lambda: self._compute_since(service_name, since), force=force)

    def get_deploy(self, service_name: str, sha_prefix: str) -> DeployRecord | None:
        """Return the single deploy for ``service_name`` matching ``sha_prefix``, or ``None``.

        Backs the deploy-sheet deep link: a slowest/fastest (or otherwise old) sha may not be in the
        loaded first page, so the page fetches that one event directly. Maps through ``_to_record``
        so ``status``/``is_rollback``/``id``/lead fields are populated exactly like the list reads.
        Read fresh (no caching) — deep links are point lookups, not a hot list.
        """
        with self._session_factory() as session:
            event = self._repository.get_by_service_and_sha(session, service_name, sha_prefix)
            return self._to_record(event) if event is not None else None

    def _compute(self, service_name: str) -> DeploymentsResponse:
        with self._session_factory() as session:
            return self._compute_page(session, service_name, cursor=None)

    def _compute_page(
        self, session: Session, service_name: str, cursor: tuple[datetime, int] | None
    ) -> DeploymentsResponse:
        events = self._repository.list_page_for_service(
            session, service_name, self._limit, before=cursor
        )
        records = [self._to_record(event) for event in events]
        # A full page means there may be more; encode the last row's keyset position. A short page
        # is the tail of this service's history -> no next cursor.
        next_cursor = (
            encode_cursor(events[-1].registered_at, events[-1].id)
            if len(events) == self._limit and events
            else None
        )
        return DeploymentsResponse(
            service=service_name,
            deployments=records,
            generated_at=self._now(),
            next_cursor=next_cursor,
        )

    def _compute_since(self, service_name: str, since: datetime) -> list[DeployRecord]:
        with self._session_factory() as session:
            events = self._repository.list_for_service_since(session, service_name, since)
            return [self._to_record(event) for event in events]

    @staticmethod
    def _to_record(event: DeployEvent) -> DeployRecord:
        return DeployRecord(
            id=event.id,
            sha=event.sha,
            image=event.image,
            revision=event.revision,
            registered_at=event.registered_at,
            author=event.author,
            author_avatar_url=event.author_avatar_url,
            message=event.message,
            commit_url=event.commit_url,
            pr_url=event.pr_url,
            committed_at=event.committed_at,
            finished_at=event.finished_at,
            status=event.status,
            is_rollback=event.is_rollback,
        )

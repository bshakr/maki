"""Data-access layer for the deploy ledger.

All SQL lives here; services never touch a Session directly.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from maki.db.models import DeployEvent, SentNotification, ServiceWatch

# Columns the ingester provides per event; the rest are DB-managed (id, ingested_at).
_UPSERTABLE_COLUMNS = (
    "service",
    "platform",
    "revision",
    "sha",
    "image",
    "registered_at",
    "committed_at",
    "finished_at",
    "author",
    "author_avatar_url",
    "message",
    "commit_url",
    "pr_url",
    "status",
    "is_rollback",
)


def _escape_like(value: str) -> str:
    """Escape LIKE wildcards in ``value`` so it matches literally (with ``escape='\\'``)."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class DeployEventRepository:
    """Thin repository over the deploy_events table."""

    def upsert_many(self, session: Session, events: Sequence[dict]) -> None:
        """Insert events, updating in place on conflict of (service, revision).

        Idempotent: re-upserting the same (service, revision) updates the row's mutable
        fields rather than creating a duplicate.
        """
        if not events:
            return

        rows = [{col: e.get(col) for col in _UPSERTABLE_COLUMNS} for e in events]
        stmt = pg_insert(DeployEvent).values(rows)
        # service/revision are the conflict key; registered_at is the immutable revision
        # registration time the ingest watermark keys off — never overwrite them on update.
        update_cols = {
            col: stmt.excluded[col]
            for col in _UPSERTABLE_COLUMNS
            if col not in ("service", "revision", "registered_at")
        }
        stmt = stmt.on_conflict_do_update(
            constraint="uq_deploy_event_service_revision",
            set_=update_cols,
        )
        session.execute(stmt)

    def list_for_service(
        self, session: Session, service: str, limit: int = 30
    ) -> list[DeployEvent]:
        """Return the newest ``limit`` events for a service, registered_at DESC."""
        stmt = (
            select(DeployEvent)
            .where(DeployEvent.service == service)
            .order_by(DeployEvent.registered_at.desc())
            .limit(limit)
        )
        return list(session.scalars(stmt))

    def list_page_for_service(
        self,
        session: Session,
        service: str,
        limit: int = 30,
        before: tuple[datetime, int] | None = None,
    ) -> list[DeployEvent]:
        """Return a keyset-paginated page of one service's events, newest registered first.

        Backs the service-detail history list's "Load more". Ordering is
        ``registered_at DESC, id DESC`` — the same sort key ``list_for_service`` uses for the card's
        first page (the displayed time is ``registered_at``), with ``id`` as a deterministic
        tiebreaker so two events sharing a registration instant always page in a fixed order.

        ``before`` is the ``(registered_at, id)`` cursor of the last row of the previous page; when
        given, only rows strictly *after* it in that ordering are returned — an earlier
        registration, or the same registration instant with a smaller ``id``. ``None`` returns the
        first page.
        """
        stmt = (
            select(DeployEvent)
            .where(DeployEvent.service == service)
            .order_by(DeployEvent.registered_at.desc(), DeployEvent.id.desc())
        )
        if before is not None:
            before_at, before_id = before
            stmt = stmt.where(
                or_(
                    DeployEvent.registered_at < before_at,
                    (DeployEvent.registered_at == before_at) & (DeployEvent.id < before_id),
                )
            )
        stmt = stmt.limit(limit)
        return list(session.scalars(stmt))

    def list_page(
        self,
        session: Session,
        limit: int = 50,
        before: tuple[datetime, int] | None = None,
    ) -> list[DeployEvent]:
        """Return a keyset-paginated page of fleet-wide events, newest go-live first.

        Backs the fleet-wide activity feed's "Load more": a chronological stream, multiple
        events per service, walked in stable pages without OFFSET drift.

        Ordering is ``COALESCE(finished_at, registered_at) DESC, id DESC`` — the go-live sort key
        (matching the feed's displayed ``deployed_at``) with ``id`` as a deterministic tiebreaker
        so two events sharing a go-live instant always page in a fixed order.

        ``before`` is the ``(deployed_at, id)`` cursor of the last row of the previous page; when
        given, only rows strictly *after* it in that ordering are returned — i.e. older go-live, or
        the same go-live with a smaller ``id``. ``None`` returns the first page.
        """
        live_at = func.coalesce(DeployEvent.finished_at, DeployEvent.registered_at)
        stmt = select(DeployEvent).order_by(live_at.desc(), DeployEvent.id.desc())
        if before is not None:
            before_live, before_id = before
            # Strictly after the cursor in (live_at DESC, id DESC): an earlier go-live, or the same
            # go-live instant but a smaller id.
            stmt = stmt.where(
                or_(
                    live_at < before_live,
                    (live_at == before_live) & (DeployEvent.id < before_id),
                )
            )
        stmt = stmt.limit(limit)
        return list(session.scalars(stmt))

    def list_around(
        self,
        session: Session,
        around: datetime,
        window: timedelta,
        max_events: int,
    ) -> list[DeployEvent]:
        """Return fleet-wide events whose go-live time falls within ``window`` of ``around``.

        Backs the activity feed's "jump to timestamp" path: during an incident the user picks a
        moment and wants to see what deployed just before/after it, across every service.

        The window is symmetric — ``[around - window, around + window]`` — so the caller always
        gets context on both sides of the target. Ordered by COALESCE(finished_at, registered_at)
        DESC to match the feed's displayed ``deployed_at`` sort key (same rationale as
        ``list_page``).

        ``max_events`` is an explicit safety bound (intentionally far higher than the default
        feed's 50) so a wide window over a busy period can't return an unbounded result set; it is
        not a silent "latest N" truncation — it caps the densest window the UI will render.
        """
        live_at = func.coalesce(DeployEvent.finished_at, DeployEvent.registered_at)
        stmt = (
            select(DeployEvent)
            .where(live_at >= around - window)
            .where(live_at <= around + window)
            .order_by(live_at.desc())
            .limit(max_events)
        )
        return list(session.scalars(stmt))

    def get_by_service_and_sha(
        self, session: Session, service: str, sha_prefix: str
    ) -> DeployEvent | None:
        """Return one event for ``service`` whose stored sha starts with ``sha_prefix``.

        Backs the deploy-sheet deep link: the URL carries the 7-char short sha while the store holds
        the full sha, so the match is a prefix (``sha LIKE :prefix%``). When more than one full sha
        shares the short prefix (rare, but possible), the newest by ``registered_at`` wins, so a
        deep link resolves to the most recent matching deploy. ``None`` when nothing matches.

        The prefix is bound as a parameter and escaped for LIKE, so no caller input is interpolated
        into the SQL or treated as a wildcard pattern.
        """
        stmt = (
            select(DeployEvent)
            .where(DeployEvent.service == service)
            .where(DeployEvent.sha.like(f"{_escape_like(sha_prefix)}%", escape="\\"))
            .order_by(DeployEvent.registered_at.desc())
            .limit(1)
        )
        return session.scalars(stmt).first()

    def list_for_service_since(
        self, session: Session, service: str, since: datetime
    ) -> list[DeployEvent]:
        """Return a service's events registered at or after ``since``, newest first."""
        stmt = (
            select(DeployEvent)
            .where(DeployEvent.service == service)
            .where(DeployEvent.registered_at >= since)
            .order_by(DeployEvent.registered_at.desc())
        )
        return list(session.scalars(stmt))

    def latest_registered_at(self, session: Session, service: str) -> datetime | None:
        """Return the newest ``registered_at`` stored for ``service`` (the ingest watermark).

        ``None`` when the deploy-events store holds nothing for the service yet.
        """
        stmt = select(func.max(DeployEvent.registered_at)).where(DeployEvent.service == service)
        return session.scalar(stmt)

    def list_services(self, session: Session) -> list[str]:
        """Return the distinct service names present in the ledger, sorted."""
        stmt = select(DeployEvent.service).distinct().order_by(DeployEvent.service)
        return list(session.scalars(stmt))

    def count_registered_since(
        self, session: Session, since: datetime, platform: str = "ecs"
    ) -> int:
        """Count events registered at/after ``since`` for one platform (fleet-wide)."""
        stmt = (
            select(func.count())
            .select_from(DeployEvent)
            .where(DeployEvent.registered_at >= since)
            .where(DeployEvent.platform == platform)
        )
        return session.execute(stmt).scalar_one()


class ServiceWatchRepository:
    """Reads and writes the opt-in set of services that produce deploy notifications."""

    def list_all(self, session: Session) -> list[ServiceWatch]:
        return list(session.scalars(select(ServiceWatch).order_by(ServiceWatch.service)))

    def get(self, session: Session, service: str) -> ServiceWatch | None:
        return session.scalars(
            select(ServiceWatch).where(ServiceWatch.service == service)
        ).one_or_none()

    def add(self, session: Session, service: str) -> ServiceWatch:
        """Start watching ``service``; returns the existing watch when already watched."""
        existing = self.get(session, service)
        if existing is not None:
            return existing
        watch = ServiceWatch(service=service)
        session.add(watch)
        session.flush()
        return watch

    def remove(self, session: Session, service: str) -> bool:
        """Stop watching ``service``; False when it wasn't watched."""
        watch = self.get(session, service)
        if watch is None:
            return False
        session.delete(watch)
        session.flush()
        return True


class SentNotificationRepository:
    """The at-most-once guard for notification delivery."""

    def claim(self, session: Session, service: str, kind: str, key: str) -> bool:
        """Record intent to notify. True when this caller won the claim and should notify."""
        stmt = (
            pg_insert(SentNotification)
            .values(service=service, kind=kind, key=key)
            .on_conflict_do_nothing(constraint="uq_sent_notification")
            .returning(SentNotification.id)
        )
        # RETURNING yields no row when the conflict suppressed the insert — a losing claim.
        return session.execute(stmt).scalar_one_or_none() is not None

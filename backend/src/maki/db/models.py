"""Declarative models for maki's deploy ledger."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class DeployEvent(Base):
    """A single deploy event for a service.

    Source of truth is an upsert keyed on (service, revision) so the background ingester
    can run repeatedly and idempotently. Amplify rows have no revision (nullable).
    """

    __tablename__ = "deploy_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service: Mapped[str] = mapped_column(String, nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String, nullable=False)  # "ecs" | "amplify"
    revision: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Amplify has none
    sha: Mapped[str | None] = mapped_column(String, nullable=True)
    image: Mapped[str | None] = mapped_column(String, nullable=True)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Normalized ECS rollout state: "in_progress" | "success" | "failed" | NULL (unknown / older
    # than ECS's ~90d service-deployment retention). is_rollback distinguishes a rollback rollout
    # from a forward deploy so the feed can render the four derivable states.
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    is_rollback: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    author: Mapped[str | None] = mapped_column(String, nullable=True)
    author_avatar_url: Mapped[str | None] = mapped_column(String, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    commit_url: Mapped[str | None] = mapped_column(String, nullable=True)
    pr_url: Mapped[str | None] = mapped_column(String, nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # NULLS NOT DISTINCT (PG 15+): Amplify rows have revision=NULL and one row per service.
        # Without this, Postgres treats every NULL as distinct, so (service, NULL) never trips
        # ON CONFLICT and the ingester would append a duplicate Amplify row every cycle.
        UniqueConstraint(
            "service",
            "revision",
            name="uq_deploy_event_service_revision",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_deploy_events_service_registered_at", "service", "registered_at"),
    )


class ServiceWatch(Base):
    """A service the operator has opted into deploy notifications for.

    ``created_at`` is the notification floor: the watcher ignores any event that finished before
    the watch existed, so adding a watch never replays history at you.
    """

    __tablename__ = "service_watches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SentNotification(Base):
    """The dedupe ledger: one row per notification actually delivered.

    The unique constraint — not in-process state — is what makes delivery at-most-once across
    restarts. The watcher INSERTs first and only notifies when the insert won.
    """

    __tablename__ = "sent_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)  # "ecs_rollout" | "ci_run"
    key: Mapped[str] = mapped_column(String, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (UniqueConstraint("service", "kind", "key", name="uq_sent_notification"),)

"""Tests for the deploy-events background ingester (mocked AWS/GitHub + live Postgres)."""

import asyncio
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy import func, select

from maki.db.models import DeployEvent
from maki.db.repository import DeployEventRepository
from maki.ingest.loop import ingest_loop
from maki.ingest.service import DeployEventIngester
from maki.schemas import CommitInfo, DeployedService, DeployRecord

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _deployed(name="api", git_sha="abc", status="COMPLETED"):
    return DeployedService(name=name, platform="ecs", git_sha=git_sha, status=status)


def _record(revision, sha, registered_at):
    return DeployRecord(
        sha=sha,
        image=f"repo:{sha}",
        revision=revision,
        registered_at=registered_at,
    )


def _commit_info(author="alice"):
    return CommitInfo(
        author=author,
        author_avatar_url=f"https://avatars/{author}.png",
        message=f"commit by {author}",
        commit_url="https://github.com/acme/platform/commit/abc",
        pr_url="https://github.com/acme/platform/pull/7",
        committed_at=NOW - timedelta(hours=1),
    )


def _make_ingester(
    *,
    session_factory,
    registry,
    history=None,
    service_deployments=None,
    amplify=None,
    enricher=None,
    ecs=None,
    overlap_seconds=3600,
    backfill_days=90,
):
    if history is None:
        history = MagicMock()
        history.list_deploys.return_value = []
    if service_deployments is None:
        service_deployments = MagicMock()
        service_deployments.state_by_revision.return_value = {}
    if enricher is None:
        enricher = MagicMock()
        enricher.commit.return_value = None
    if ecs is None:
        ecs = MagicMock()
        ecs.describe_services.return_value = {
            "services": [{"taskDefinition": "arn:aws:ecs:eu-west-1:1:task-definition/api:9"}]
        }
    return DeployEventIngester(
        registry=registry,
        history=history,
        service_deployments=service_deployments,
        amplify=amplify,
        enricher=enricher,
        repo_for=lambda name: "acme/platform",
        repository=DeployEventRepository(),
        session_factory=session_factory,
        ecs_client=ecs,
        cluster="production",
        backfill_days=backfill_days,
        overlap_seconds=overlap_seconds,
        max_revisions_per_service=1000,
        now=lambda: NOW,
    )


def _count(session) -> int:
    return session.scalar(select(func.count()).select_from(DeployEvent))


def test_cycle_upserts_events_with_full_field_mapping(session, session_factory):
    registry = MagicMock()
    registry.list_deployed_services.return_value = [_deployed(name="api")]

    history = MagicMock()
    history.list_deploys.return_value = [_record(9, "abc", NOW - timedelta(hours=2))]

    service_deployments = MagicMock()
    service_deployments.state_by_revision.return_value = {
        9: {"finished_at": NOW - timedelta(minutes=30), "status": "SUCCESSFUL"}
    }

    enricher = MagicMock()
    enricher.commit.return_value = _commit_info("alice")

    ingester = _make_ingester(
        session_factory=session_factory,
        registry=registry,
        history=history,
        service_deployments=service_deployments,
        enricher=enricher,
    )
    ingester.run_once()

    row = session.scalars(select(DeployEvent).where(DeployEvent.service == "api")).one()
    assert row.platform == "ecs"
    assert row.revision == 9
    assert row.sha == "abc"
    assert row.image == "repo:abc"
    assert row.registered_at == NOW - timedelta(hours=2)
    assert row.finished_at == NOW - timedelta(minutes=30)
    assert row.status == "success"
    assert row.is_rollback is False
    assert row.author == "alice"
    assert row.author_avatar_url == "https://avatars/alice.png"
    assert row.message == "commit by alice"
    assert row.pr_url == "https://github.com/acme/platform/pull/7"
    assert row.committed_at == NOW - timedelta(hours=1)


def test_rollback_status_threads_through_to_row(session, session_factory):
    registry = MagicMock()
    registry.list_deployed_services.return_value = [_deployed(name="api")]

    history = MagicMock()
    history.list_deploys.return_value = [_record(9, "abc", NOW - timedelta(hours=2))]

    service_deployments = MagicMock()
    service_deployments.state_by_revision.return_value = {
        9: {"finished_at": NOW - timedelta(minutes=5), "status": "ROLLBACK_SUCCESSFUL"}
    }

    ingester = _make_ingester(
        session_factory=session_factory,
        registry=registry,
        history=history,
        service_deployments=service_deployments,
    )
    ingester.run_once()

    row = session.scalars(select(DeployEvent).where(DeployEvent.service == "api")).one()
    assert row.status == "success"
    assert row.is_rollback is True


def test_ecs_event_carries_status_and_is_rollback():
    record = _record(9, "abc", NOW)
    record.status = "in_progress"
    record.is_rollback = True
    event = DeployEventIngester._ecs_event("api", record)
    assert event["status"] == "in_progress"
    assert event["is_rollback"] is True


def test_unknown_status_persists_as_null(session, session_factory):
    registry = MagicMock()
    registry.list_deployed_services.return_value = [_deployed(name="api")]

    history = MagicMock()
    history.list_deploys.return_value = [_record(9, "abc", NOW - timedelta(hours=2))]

    # Revision older than ECS retention -> no entry in state map -> status stays NULL.
    service_deployments = MagicMock()
    service_deployments.state_by_revision.return_value = {}

    ingester = _make_ingester(
        session_factory=session_factory,
        registry=registry,
        history=history,
        service_deployments=service_deployments,
    )
    ingester.run_once()

    row = session.scalars(select(DeployEvent).where(DeployEvent.service == "api")).one()
    assert row.status is None
    assert row.is_rollback is False
    assert row.finished_at is None


def test_run_once_is_idempotent(session, session_factory):
    registry = MagicMock()
    registry.list_deployed_services.return_value = [_deployed(name="api")]

    history = MagicMock()
    enricher = MagicMock()

    ingester = _make_ingester(
        session_factory=session_factory,
        registry=registry,
        history=history,
        enricher=enricher,
    )

    history.list_deploys.return_value = [_record(9, "abc", NOW - timedelta(hours=2))]
    enricher.commit.return_value = _commit_info("alice")
    ingester.run_once()
    session.flush()
    assert _count(session) == 1

    # Second cycle: same revision, mutated commit metadata -> update in place, no dupes.
    history.list_deploys.return_value = [_record(9, "abc", NOW - timedelta(hours=2))]
    enricher.commit.return_value = _commit_info("bob")
    ingester.run_once()
    session.flush()

    assert _count(session) == 1
    row = session.scalars(select(DeployEvent).where(DeployEvent.revision == 9)).one()
    assert row.author == "bob"


def test_failure_isolation_one_service_does_not_block_others(session, session_factory):
    registry = MagicMock()
    registry.list_deployed_services.return_value = [
        _deployed(name="bad"),
        _deployed(name="good"),
    ]

    history = MagicMock()

    def list_deploys(family, **kwargs):
        if family == "bad":
            raise RuntimeError("AWS blew up for bad")
        return [_record(3, "good-sha", NOW - timedelta(hours=1))]

    history.list_deploys.side_effect = list_deploys

    ecs = MagicMock()

    def describe_services(cluster, services):
        name = services[0]
        return {"services": [{"taskDefinition": f"arn:...:task-definition/{name}:5"}]}

    ecs.describe_services.side_effect = describe_services

    ingester = _make_ingester(
        session_factory=session_factory,
        registry=registry,
        history=history,
        ecs=ecs,
    )
    ingester.run_once()
    session.flush()

    services = {row.service for row in session.scalars(select(DeployEvent))}
    assert services == {"good"}


def test_watermark_drives_since_on_second_run(session, session_factory):
    registry = MagicMock()
    registry.list_deployed_services.return_value = [_deployed(name="api")]

    history = MagicMock()
    enricher = MagicMock()
    enricher.commit.return_value = None

    overlap = 3600
    ingester = _make_ingester(
        session_factory=session_factory,
        registry=registry,
        history=history,
        enricher=enricher,
        overlap_seconds=overlap,
        backfill_days=90,
    )

    watermark = NOW - timedelta(hours=2)
    history.list_deploys.return_value = [_record(9, "abc", watermark)]
    ingester.run_once()
    session.flush()

    # First run: cold store -> since = now - backfill_days.
    first_since = history.list_deploys.call_args.kwargs["since"]
    assert first_since == NOW - timedelta(days=90)

    history.list_deploys.reset_mock()
    history.list_deploys.return_value = []
    ingester.run_once()

    # Second run: since = max(registered_at) - overlap.
    second_since = history.list_deploys.call_args.kwargs["since"]
    assert second_since == watermark - timedelta(seconds=overlap)


def test_amplify_event_upserted_with_null_revision(session, session_factory):
    registry = MagicMock()
    registry.list_deployed_services.return_value = []  # no ECS services

    amplify = MagicMock()
    amplify.get_deployed_web_app.return_value = DeployedService(
        name="web-app",
        platform="amplify",
        git_sha="websha",
        deployed_at=NOW - timedelta(minutes=10),
        status="SUCCEED",
    )

    enricher = MagicMock()
    enricher.commit.return_value = _commit_info("carol")

    ingester = _make_ingester(
        session_factory=session_factory,
        registry=registry,
        amplify=amplify,
        enricher=enricher,
    )
    ingester.run_once()
    session.flush()

    row = session.scalars(select(DeployEvent).where(DeployEvent.service == "web-app")).one()
    assert row.platform == "amplify"
    assert row.revision is None
    assert row.sha == "websha"
    assert row.author == "carol"
    assert row.status == "success"  # Amplify SUCCEED -> success
    assert row.is_rollback is False


def test_amplify_upsert_is_idempotent_across_cycles(session, session_factory):
    # Amplify rows have revision=NULL. With a default NULLS DISTINCT unique constraint,
    # Postgres treats every (web-app, NULL) as distinct so ON CONFLICT never fires and each
    # cycle appends a duplicate. The constraint is NULLS NOT DISTINCT precisely to prevent
    # this — two cycles must leave exactly one row.
    registry = MagicMock()
    registry.list_deployed_services.return_value = []

    amplify = MagicMock()
    amplify.get_deployed_web_app.return_value = DeployedService(
        name="web-app",
        platform="amplify",
        git_sha="websha",
        deployed_at=NOW - timedelta(minutes=10),
        status="SUCCEED",
    )
    enricher = MagicMock()
    enricher.commit.return_value = _commit_info("carol")

    ingester = _make_ingester(
        session_factory=session_factory,
        registry=registry,
        amplify=amplify,
        enricher=enricher,
    )
    ingester.run_once()
    session.flush()
    assert _count(session) == 1

    ingester.run_once()
    session.flush()
    assert _count(session) == 1


def test_amplify_without_deploy_time_is_skipped(session, session_factory):
    # registered_at is NOT NULL; an Amplify web app with no deployed_at must be skipped
    # rather than raising an IntegrityError the per-service except would swallow.
    registry = MagicMock()
    registry.list_deployed_services.return_value = []

    amplify = MagicMock()
    amplify.get_deployed_web_app.return_value = DeployedService(
        name="web-app", platform="amplify", git_sha="websha", deployed_at=None, status="PENDING"
    )

    ingester = _make_ingester(
        session_factory=session_factory,
        registry=registry,
        amplify=amplify,
    )
    ingester.run_once()
    session.flush()
    assert _count(session) == 0


def test_failure_row_from_registry_is_skipped(session, session_factory):
    registry = MagicMock()
    registry.list_deployed_services.return_value = [
        DeployedService(name="broken", platform="ecs", status="unavailable: MISSING"),
        _deployed(name="api"),
    ]
    history = MagicMock()
    history.list_deploys.return_value = [_record(1, "s", NOW - timedelta(hours=1))]

    ingester = _make_ingester(
        session_factory=session_factory,
        registry=registry,
        history=history,
    )
    ingester.run_once()
    session.flush()

    services = {row.service for row in session.scalars(select(DeployEvent))}
    assert services == {"api"}


def test_cancelling_the_loop_returns_promptly_mid_cycle():
    # Lifespan shutdown cancels the loop task. Even if a cycle is mid-flight on the worker
    # thread (the first cycle is a long backfill), cancellation must unblock the await
    # immediately rather than waiting for run_once to finish — otherwise shutdown/--reload wedges.
    async def _run():
        ingester = MagicMock()
        ingester.run_once.side_effect = lambda: time.sleep(2.0)  # a slow cycle
        stop = asyncio.Event()
        task = asyncio.create_task(ingest_loop(ingester, interval_seconds=0.01, stop=stop))
        await asyncio.sleep(0.05)  # let it enter run_once on the thread
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            # Must resolve well before the 2s cycle would finish.
            await asyncio.wait_for(task, timeout=0.5)

    asyncio.run(_run())


def test_ingest_loop_runs_once_then_stops():
    ingester = MagicMock()
    stop = asyncio.Event()

    def run_once():
        stop.set()  # stop after the first cycle

    ingester.run_once.side_effect = run_once

    asyncio.run(ingest_loop(ingester, interval_seconds=0.01, stop=stop))

    ingester.run_once.assert_called_once()

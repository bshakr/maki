"""The background ingester for maki's deploy-events store.

One ``run_once()`` cycle snapshots every currently-deployed ECS service (plus the Amplify web
app), enriches each task-def revision with GitHub commit metadata, resolves the accurate
"live in prod" time from ECS service deployments, and upserts the result into ``deploy_events``.

The ingester is the sole AWS caller for deploy history. It is idempotent: the unique constraint
plus ``ON CONFLICT DO UPDATE`` in the repository means re-running never duplicates rows.

All AWS access is read-only (list/describe). Dependencies are injected so tests can pass mocks.
"""

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from maki.aws.amplify_registry import AmplifyDeployRegistry
from maki.aws.clients import amplify_client, ecs_client
from maki.aws.ecs_history import ECSDeployHistory
from maki.aws.ecs_registry import ECSDeployRegistry
from maki.aws.service_deployments import ECSServiceDeployments
from maki.db.engine import get_session
from maki.db.repository import DeployEventRepository
from maki.deploy_status import normalize_status
from maki.github_enrich import GitHubEnricher
from maki.schemas import DeployedService, DeployRecord
from maki.settings import settings

logger = logging.getLogger(__name__)

# Amplify deploy-job statuses -> normalized feed status. is_rollback is always False for Amplify.
_AMPLIFY_STATUS = {
    "SUCCEED": "success",
    "FAILED": "failed",
    "RUNNING": "in_progress",
    "PENDING": "in_progress",
}


class DeployEventIngester:
    """Snapshot AWS deploy state into the deploy-events store, idempotently."""

    def __init__(
        self,
        *,
        registry: ECSDeployRegistry,
        history: ECSDeployHistory,
        service_deployments: ECSServiceDeployments,
        amplify: AmplifyDeployRegistry | None,
        enricher: GitHubEnricher,
        repo_for: Callable[[str], str | None],
        repository: DeployEventRepository,
        session_factory: Callable[[], AbstractContextManager[Session]],
        ecs_client,
        cluster: str,
        backfill_days: int,
        overlap_seconds: int,
        max_revisions_per_service: int,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._registry = registry
        self._history = history
        self._service_deployments = service_deployments
        self._amplify = amplify
        self._enricher = enricher
        self._repo_for = repo_for
        self._repository = repository
        self._session_factory = session_factory
        self._ecs = ecs_client
        self._cluster = cluster
        self._backfill_days = backfill_days
        self._overlap_seconds = overlap_seconds
        self._max_revisions = max_revisions_per_service
        self._now = now

    def run_once(self) -> None:
        """Run one ingest cycle: ECS services + Amplify -> upsert into the deploy-events store.

        Per-service failures are isolated (logged, the session rolled back to before that
        service's writes) so one bad service never aborts the run or loses other services' rows.
        """
        with self._session_factory() as session:
            for service in self._registry.list_deployed_services():
                self._ingest_ecs_service(session, service)
            self._ingest_amplify(session)

    def _ingest_ecs_service(self, session: Session, service: DeployedService) -> None:
        name = service.name
        # Failure/placeholder rows from the registry carry a status but no usable deploy state
        # (no git_sha, no current revision); they are not real services to ingest.
        if not name or self._is_failure_row(service):
            return
        try:
            family = self._family_for(name)
            if not family:
                logger.debug("no task-def family for service %r; skipping", name)
                return

            since = self._since_for(session, name)
            records = self._history.list_deploys(
                family, since=since, max_revisions=self._max_revisions
            )
            self._enrich(name, records)
            self._populate_rollout_state(name, family, records)

            events = [self._ecs_event(name, record) for record in records]
            self._repository.upsert_many(session, events)
            session.commit()
        except Exception:
            session.rollback()
            logger.warning("ingest failed for ECS service %r; continuing", name, exc_info=True)

    def _ingest_amplify(self, session: Session) -> None:
        if self._amplify is None:
            return
        try:
            web = self._amplify.get_deployed_web_app()
            if web is None or web.deployed_at is None:
                # No web app, or no deploy time to anchor registered_at (NOT NULL). Skip rather
                # than raise an IntegrityError that the except below would silently swallow.
                return
            event = self._amplify_event(web)
            self._repository.upsert_many(session, [event])
            session.commit()
        except Exception:
            session.rollback()
            logger.warning("ingest failed for Amplify web app; continuing", exc_info=True)

    def _since_for(self, session: Session, service_name: str) -> datetime:
        """The watermark: newest stored ``registered_at`` minus overlap, else the backfill window.

        The overlap re-reads a small recent slice so a revision registered right at the previous
        cutoff is never skipped. A cold store backfills the full window.
        """
        watermark = self._repository.latest_registered_at(session, service_name)
        if watermark is None:
            return self._now() - timedelta(days=self._backfill_days)
        return watermark - timedelta(seconds=self._overlap_seconds)

    def _enrich(self, service_name: str, records: list[DeployRecord]) -> None:
        repo = self._repo_for(service_name)
        for record in records:
            if record.sha:
                info = self._enricher.commit(repo, record.sha)
                if info:
                    record.author = info.author
                    record.author_avatar_url = info.author_avatar_url
                    record.message = info.message
                    record.commit_url = info.commit_url
                    record.pr_url = info.pr_url
                    record.committed_at = info.committed_at

    def _populate_rollout_state(
        self, service_name: str, family: str, records: list[DeployRecord]
    ) -> None:
        """Set ``finished_at`` (live-in-prod time) + normalized ``status``/``is_rollback`` per
        record from ECS service deployments, in a single best-effort pass.

        Bounded by ECS's ~90-day retention; revisions older than the window keep ``finished_at``
        None and ``status`` None (honest: no lead time / status rather than a guess).
        """
        since = self._now() - timedelta(days=self._backfill_days)
        state_by_revision = self._service_deployments.state_by_revision(
            service_name, since, family
        )
        for record in records:
            if record.revision is None:
                continue
            state = state_by_revision.get(record.revision)
            if state is None:
                continue
            record.finished_at = state.get("finished_at")
            record.status, record.is_rollback = normalize_status(state.get("status"))

    def _family_for(self, service_name: str) -> str | None:
        resp = self._ecs.describe_services(cluster=self._cluster, services=[service_name])
        services = resp.get("services", [])
        if not services:
            return None
        arn = services[0].get("taskDefinition")
        return ECSDeployHistory.family_from_arn(arn) if arn else None

    @staticmethod
    def _is_failure_row(service: DeployedService) -> bool:
        # _failure_row / _safe_map in ECSDeployRegistry mark unusable services with a status
        # prefixed "unavailable:" or "error:" and no git_sha.
        status = service.status or ""
        return service.git_sha is None and (
            status.startswith("unavailable:") or status.startswith("error:")
        )

    @staticmethod
    def _ecs_event(service_name: str, record: DeployRecord) -> dict:
        return {
            "service": service_name,
            "platform": "ecs",
            "revision": record.revision,
            "sha": record.sha,
            "image": record.image,
            "registered_at": record.registered_at,
            "committed_at": record.committed_at,
            "finished_at": record.finished_at,
            "author": record.author,
            "author_avatar_url": record.author_avatar_url,
            "message": record.message,
            "commit_url": record.commit_url,
            "pr_url": record.pr_url,
            "status": record.status,
            "is_rollback": record.is_rollback,
        }

    def _amplify_event(self, web: DeployedService) -> dict:
        sha = web.git_sha
        info = self._enricher.commit(self._repo_for(web.name), sha) if sha else None
        # AmplifyDeployRegistry already surfaces the active job's status (SUCCEED/FAILED/RUNNING)
        # on DeployedService.status. Map it best-effort; unknown/absent -> None. Amplify has no
        # rollback concept here, so is_rollback is always False.
        status = _AMPLIFY_STATUS.get(web.status or "")
        return {
            "service": web.name,
            "platform": "amplify",
            "revision": None,
            "sha": sha,
            "image": web.image,
            "registered_at": web.deployed_at,
            "committed_at": info.committed_at if info else None,
            "finished_at": web.deployed_at,
            "author": info.author if info else None,
            "author_avatar_url": info.author_avatar_url if info else None,
            "message": info.message if info else None,
            "commit_url": info.commit_url if info else None,
            "pr_url": info.pr_url if info else None,
            "status": status,
            "is_rollback": False,
        }


def build_ingester() -> DeployEventIngester:
    """Construct a ``DeployEventIngester`` wired to real AWS/GitHub clients and maki's Postgres.

    Called only when the app actually starts the ingest loop (see ``api.lifespan``), so importing
    this module never touches AWS or the database.
    """
    ecs = ecs_client()
    # Amplify is optional: skip it when disabled OR when enabled but no app id is configured, so the
    # ingester degrades to ECS-only rather than erroring on get_branch(appId=None) every cycle.
    amplify: AmplifyDeployRegistry | None = None
    app_id = settings.amplify_app_id
    if settings.amplify_enabled and app_id:
        amplify = AmplifyDeployRegistry(
            amplify_client(),
            app_id,
            settings.amplify_branch,
            service_name=settings.amplify_service_name,
        )
    return DeployEventIngester(
        registry=ECSDeployRegistry(ecs, settings.ecs_cluster, region=settings.aws_region),
        history=ECSDeployHistory(ecs),
        service_deployments=ECSServiceDeployments(ecs, settings.ecs_cluster),
        amplify=amplify,
        enricher=GitHubEnricher(settings.github_token, settings.github_api_url),
        repo_for=settings.repo_for,
        repository=DeployEventRepository(),
        session_factory=get_session,
        ecs_client=ecs,
        cluster=settings.ecs_cluster,
        backfill_days=settings.ingest_backfill_days,
        overlap_seconds=settings.ingest_overlap_seconds,
        max_revisions_per_service=settings.ingest_max_revisions_per_service,
    )

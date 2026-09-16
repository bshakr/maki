"""The fast watcher for opted-in services.

One ``run_once()`` cycle checks each watched service's ECS rollouts and its repo's failed CI
deploy jobs, claims each notification-worthy event in the dedupe ledger, and notifies only on a
won claim. All AWS/GitHub access is read-only.
"""

import logging
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from maki.aws.clients import ecs_client
from maki.aws.ecs_history import ECSDeployHistory
from maki.aws.service_deployments import ECSServiceDeployments
from maki.db.engine import get_session
from maki.db.repository import SentNotificationRepository, ServiceWatchRepository
from maki.deploy_status import TERMINAL_STATUSES, normalize_status
from maki.github_actions import GitHubActions
from maki.github_enrich import GitHubEnricher
from maki.notifications.jobs import is_deploy_job_for
from maki.notifications.notifier import Notifier, build_notifier
from maki.settings import settings

logger = logging.getLogger(__name__)


class DeployWatcher:
    """Notify the operator about deploys of watched services, at most once per event."""

    def __init__(
        self,
        *,
        ecs_client,
        cluster: str,
        service_deployments: ECSServiceDeployments,
        history: ECSDeployHistory,
        enricher: GitHubEnricher,
        github: GitHubActions,
        repo_for: Callable[[str], str | None],
        deploy_job_prefixes: Sequence[str],
        deploy_job_suffixes: Sequence[str],
        watches: ServiceWatchRepository,
        sent: SentNotificationRepository,
        session_factory: Callable[[], AbstractContextManager[Session]],
        notifier: Notifier,
        base_url: str,
        lookback: timedelta,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._ecs = ecs_client
        self._cluster = cluster
        self._service_deployments = service_deployments
        self._history = history
        self._enricher = enricher
        self._github = github
        self._repo_for = repo_for
        self._prefixes = deploy_job_prefixes
        self._suffixes = deploy_job_suffixes
        self._watches = watches
        self._sent = sent
        self._session_factory = session_factory
        self._notifier = notifier
        self._base_url = base_url.rstrip("/")
        self._lookback = lookback
        self._now = now

    def run_once(self) -> None:
        """Run one watch cycle over every watched service.

        Each check isolates its own failures, per service and per source: expired AWS credentials
        are the routine daily case on an SSO-backed laptop, and they must not take GitHub's CI
        failures down with them. Claims are committed before their notification, so neither
        check's rollback can resurrect an event that was already notified.
        """
        with self._session_factory() as session:
            # Read the watches out up front: a check's rollback expires every loaded instance,
            # and a later attribute access would silently re-query mid-cycle.
            watches = [(w.service, w.created_at) for w in self._watches.list_all(session)]
            for service, watched_since in watches:
                self._check_ecs(session, service, watched_since)
                self._check_ci(session, service, watched_since)

    def _scan_since(self) -> datetime:
        """The API-level window. Both sources filter on CREATION time, so this must not be floored
        at the watch: the deploy the operator opts in to hear about is usually already running.
        Completion time is what decides whether an event is history."""
        return self._now() - self._lookback

    def _check_ecs(self, session: Session, service: str, watched_since: datetime) -> None:
        try:
            family = self._family_for(service)
            if not family:
                logger.debug("no task-def family for service %r; skipping", service)
                return
            states = self._service_deployments.state_by_revision(
                service, self._scan_since(), family
            )
            for revision, state in sorted(states.items()):
                status, is_rollback = normalize_status(state.get("status"))
                finished_at = state.get("finished_at")
                if status not in TERMINAL_STATUSES or finished_at is None:
                    continue
                if finished_at <= watched_since:
                    continue
                # The status is part of the key: a revision that fails and is then redeployed
                # successfully is two events the operator wants to hear about.
                if not self._claim(session, service, "ecs_rollout", f"{revision}:{status}"):
                    continue
                self._notify_rollout(service, family, revision, status, is_rollback)
        except Exception:
            session.rollback()
            logger.warning("ECS watch failed for %r; continuing", service, exc_info=True)

    def _check_ci(self, session: Session, service: str, watched_since: datetime) -> None:
        repo = self._repo_for(service)
        if not repo:
            logger.debug("no repo mapped for service %r; skipping CI check", service)
            return
        try:
            for run in self._github.recent_failed_runs(repo, self._scan_since()):
                finished_at = run.get("updated_at")
                # An unparseable timestamp is treated as "just failed": the claim ledger makes a
                # stale notification at worst a one-off, a dropped one is invisible forever.
                if finished_at is not None and finished_at <= watched_since:
                    continue
                failed = [
                    job
                    for job in self._github.jobs_for_run(repo, run["id"])
                    if job.get("conclusion") == "failure"
                ]
                deploy_jobs = [
                    job
                    for job in failed
                    if is_deploy_job_for(
                        job.get("name") or "", service, self._prefixes, self._suffixes
                    )
                ]
                if not deploy_jobs:
                    if failed:
                        # A job name no naming rule bridges (deploy-entity-sync-batch rolls out
                        # prod-...-employee-sync-batch) would otherwise look like a green repo.
                        logger.debug(
                            "run %s: failed jobs %s match no deploy job for %r",
                            run["id"],
                            [job.get("name") for job in failed],
                            service,
                        )
                    continue
                if not self._claim(session, service, "ci_run", str(run["id"])):
                    continue
                self._notifier.notify(
                    title=f"{service} CI deploy failed",
                    subtitle=deploy_jobs[0].get("name"),
                    body=run.get("name") or repo,
                    url=deploy_jobs[0].get("html_url") or run.get("html_url"),
                )
        except Exception:
            session.rollback()
            logger.warning("CI watch failed for %r; continuing", service, exc_info=True)

    def _claim(self, session: Session, service: str, kind: str, key: str) -> bool:
        """Claim and COMMIT before notifying, so a crash can only lose a notification, never
        duplicate one."""
        if not self._sent.claim(session, service, kind, key):
            return False
        session.commit()
        return True

    def _family_for(self, service_name: str) -> str | None:
        resp = self._ecs.describe_services(cluster=self._cluster, services=[service_name])
        services = resp.get("services", [])
        if not services:
            return None
        arn = services[0].get("taskDefinition")
        return ECSDeployHistory.family_from_arn(arn) if arn else None

    def _notify_rollout(
        self, service: str, family: str, revision: int, status: str, is_rollback: bool
    ) -> None:
        sha = self._sha_for(family, revision)
        if status == "failed":
            title = f"{service} deploy FAILED"
        elif is_rollback:
            title = f"{service} rolled back"
        else:
            title = f"{service} deployed"
        self._notifier.notify(
            title=title,
            subtitle=sha[:7] if sha else f"rev {revision}",
            body=self._message_for(service, sha) or f"revision {revision}",
            # The service page, not a deploy-detail route: it always exists, whereas the
            # deploy-detail URL needs a sha that best-effort enrichment may not have.
            url=f"{self._base_url}/services/{service}",
        )

    def _sha_for(self, family: str, revision: int) -> str | None:
        """Best-effort sha for a revision. The watcher runs far more often than the ingester, so
        the stored deploy event may not exist yet — enrichment must never hold up a notification.
        """
        try:
            records = self._history.list_deploys(
                family, since=self._now() - self._lookback, max_revisions=10
            )
            for record in records:
                if record.revision == revision:
                    return record.sha
        except Exception:
            logger.debug("sha lookup failed for %s rev %s", family, revision, exc_info=True)
        return None

    def _message_for(self, service: str, sha: str | None) -> str | None:
        if not sha:
            return None
        try:
            info = self._enricher.commit(self._repo_for(service), sha)
            return info.message.splitlines()[0] if info and info.message else None
        except Exception:
            logger.debug("commit enrichment failed for %s %s", service, sha, exc_info=True)
            return None


def build_watcher() -> DeployWatcher:
    """Construct a ``DeployWatcher`` wired to real AWS/GitHub clients and maki's Postgres.

    Called only when the app actually starts the watch loop, so importing this module never
    touches AWS or the database.
    """
    ecs = ecs_client()
    # The timeline's rollout-job markers double as the watcher's "is this the job that deploys
    # my service" rule — one convention, configured once.
    job_markers = settings.config.deployTimeline.github
    return DeployWatcher(
        ecs_client=ecs,
        cluster=settings.ecs_cluster,
        service_deployments=ECSServiceDeployments(ecs, settings.ecs_cluster),
        history=ECSDeployHistory(ecs),
        enricher=GitHubEnricher(settings.github_token, settings.github_api_url),
        github=GitHubActions(settings.github_token, settings.github_api_url),
        repo_for=settings.repo_for,
        deploy_job_prefixes=job_markers.hideJobsStartingWith,
        deploy_job_suffixes=job_markers.hideJobsEndingWith,
        watches=ServiceWatchRepository(),
        sent=SentNotificationRepository(),
        session_factory=get_session,
        notifier=build_notifier(),
        base_url=settings.maki_base_url,
        lookback=timedelta(minutes=settings.watch_lookback_minutes),
    )

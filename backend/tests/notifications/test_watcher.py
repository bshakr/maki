from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from maki.db.repository import SentNotificationRepository, ServiceWatchRepository
from maki.notifications.watcher import DeployWatcher

NOW = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
WATCHED_AT = NOW - timedelta(hours=1)


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def notify(self, *, title, subtitle, body, url):
        self.sent.append({"title": title, "subtitle": subtitle, "body": body, "url": url})


def _watcher(*, session_factory, session, notifier, states=None, runs=None, jobs=None):
    watch = ServiceWatchRepository().add(session, "insights")
    # created_at is a server_default (real wall clock); pin it so the cold-start floor the
    # watcher compares against is the same frozen clock the fixtures are built off.
    watch.created_at = WATCHED_AT
    session.flush()

    service_deployments = MagicMock()
    service_deployments.state_by_revision.return_value = states or {}

    github = MagicMock()
    github.recent_failed_runs.return_value = runs or []
    github.jobs_for_run.return_value = jobs or []

    ecs = MagicMock()
    ecs.describe_services.return_value = {
        "services": [{"taskDefinition": "arn:aws:ecs:eu-west-1:1:task-definition/insights:42"}]
    }

    history = MagicMock()
    history.list_deploys.return_value = []

    return DeployWatcher(
        ecs_client=ecs,
        cluster="prod",
        service_deployments=service_deployments,
        history=history,
        enricher=MagicMock(),
        github=github,
        repo_for=lambda _: "acme/platform",
        deploy_job_prefixes=["deploy-"],
        deploy_job_suffixes=["deploy"],
        watches=ServiceWatchRepository(),
        sent=SentNotificationRepository(),
        session_factory=session_factory,
        notifier=notifier,
        lookback=timedelta(hours=2),
        now=lambda: NOW,
    )


def test_notifies_once_for_a_successful_rollout(session_factory, session):
    notifier = FakeNotifier()
    states = {42: {"status": "SUCCESSFUL", "finished_at": NOW - timedelta(minutes=5)}}
    watcher = _watcher(
        session_factory=session_factory, session=session, notifier=notifier, states=states
    )

    watcher.run_once()
    watcher.run_once()

    assert len(notifier.sent) == 1
    assert "insights" in notifier.sent[0]["title"]
    assert "deployed" in notifier.sent[0]["title"]


def test_notifies_for_a_failed_rollout(session_factory, session):
    notifier = FakeNotifier()
    states = {42: {"status": "STOPPED", "finished_at": NOW - timedelta(minutes=5)}}
    _watcher(
        session_factory=session_factory, session=session, notifier=notifier, states=states
    ).run_once()

    assert "FAILED" in notifier.sent[0]["title"]


def test_names_a_rollback_distinctly(session_factory, session):
    notifier = FakeNotifier()
    states = {42: {"status": "ROLLBACK_SUCCESSFUL", "finished_at": NOW - timedelta(minutes=5)}}
    _watcher(
        session_factory=session_factory, session=session, notifier=notifier, states=states
    ).run_once()

    assert "rolled back" in notifier.sent[0]["title"]


def test_ignores_events_that_finished_before_the_watch_existed(session_factory, session):
    notifier = FakeNotifier()
    states = {42: {"status": "SUCCESSFUL", "finished_at": WATCHED_AT - timedelta(minutes=30)}}
    _watcher(
        session_factory=session_factory, session=session, notifier=notifier, states=states
    ).run_once()

    assert notifier.sent == []


def test_ignores_in_progress_rollouts(session_factory, session):
    notifier = FakeNotifier()
    states = {42: {"status": "IN_PROGRESS", "finished_at": None}}
    _watcher(
        session_factory=session_factory, session=session, notifier=notifier, states=states
    ).run_once()

    assert notifier.sent == []


def test_failed_then_succeeded_notifies_twice(session_factory, session):
    notifier = FakeNotifier()
    watcher = _watcher(
        session_factory=session_factory,
        session=session,
        notifier=notifier,
        states={42: {"status": "STOPPED", "finished_at": NOW - timedelta(minutes=9)}},
    )
    watcher.run_once()
    watcher._service_deployments.state_by_revision.return_value = {
        42: {"status": "SUCCESSFUL", "finished_at": NOW - timedelta(minutes=2)}
    }
    watcher.run_once()

    assert len(notifier.sent) == 2


def test_a_claim_survives_a_later_failure_in_the_same_cycle(session_factory, session):
    """The claim is committed before the notification, so the cycle's rollback cannot undo it."""
    notifier = FakeNotifier()
    states = {42: {"status": "SUCCESSFUL", "finished_at": NOW - timedelta(minutes=5)}}
    watcher = _watcher(
        session_factory=session_factory, session=session, notifier=notifier, states=states
    )
    watcher._github.recent_failed_runs.side_effect = RuntimeError("boom")

    watcher.run_once()
    watcher._github.recent_failed_runs.side_effect = None
    watcher.run_once()

    assert len(notifier.sent) == 1


def test_notifies_for_a_failed_ci_deploy_job(session_factory, session):
    notifier = FakeNotifier()
    runs = [
        {
            "id": 7,
            "name": "deploy",
            "head_sha": "a" * 40,
            "html_url": "http://run/7",
            "created_at": NOW - timedelta(minutes=10),
            "updated_at": NOW - timedelta(minutes=8),
        }
    ]
    jobs = [{"name": "deploy-insights", "conclusion": "failure", "html_url": "http://job"}]
    watcher = _watcher(
        session_factory=session_factory,
        session=session,
        notifier=notifier,
        runs=runs,
        jobs=jobs,
    )

    watcher.run_once()
    watcher.run_once()

    assert len(notifier.sent) == 1
    assert "CI" in notifier.sent[0]["title"]
    assert notifier.sent[0]["url"] == "http://job"


def test_ignores_a_failed_job_for_a_sibling_service(session_factory, session):
    notifier = FakeNotifier()
    runs = [
        {
            "id": 7,
            "name": "deploy",
            "head_sha": "a" * 40,
            "html_url": "http://run/7",
            "created_at": NOW - timedelta(minutes=10),
            "updated_at": NOW - timedelta(minutes=8),
        }
    ]
    jobs = [{"name": "deploy-worker", "conclusion": "failure", "html_url": "http://job"}]
    _watcher(
        session_factory=session_factory, session=session, notifier=notifier, runs=runs, jobs=jobs
    ).run_once()

    assert notifier.sent == []


def test_logs_the_failed_jobs_that_matched_no_watched_service(session_factory, session, caplog):
    notifier = FakeNotifier()
    runs = [
        {
            "id": 7,
            "name": "deploy",
            "head_sha": "a" * 40,
            "html_url": "http://run/7",
            "created_at": NOW - timedelta(minutes=10),
            "updated_at": NOW - timedelta(minutes=8),
        }
    ]
    jobs = [{"name": "deploy-worker", "conclusion": "failure", "html_url": "http://job"}]
    with caplog.at_level("DEBUG", logger="maki.notifications.watcher"):
        _watcher(
            session_factory=session_factory,
            session=session,
            notifier=notifier,
            runs=runs,
            jobs=jobs,
        ).run_once()

    assert "deploy-worker" in caplog.text


def test_one_services_failure_does_not_abort_the_cycle(session_factory, session):
    notifier = FakeNotifier()
    watcher = _watcher(session_factory=session_factory, session=session, notifier=notifier)
    watcher._ecs.describe_services.side_effect = RuntimeError("boom")

    watcher.run_once()

    assert notifier.sent == []

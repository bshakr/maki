from maki.db.repository import SentNotificationRepository, ServiceWatchRepository

watches = ServiceWatchRepository()
sent = SentNotificationRepository()


def test_add_then_list(session):
    watches.add(session, "insights")
    assert [w.service for w in watches.list_all(session)] == ["insights"]


def test_add_is_idempotent(session):
    first = watches.add(session, "insights")
    again = watches.add(session, "insights")
    assert first.id == again.id
    assert len(watches.list_all(session)) == 1


def test_remove_reports_whether_it_existed(session):
    watches.add(session, "insights")
    assert watches.remove(session, "insights") is True
    assert watches.remove(session, "insights") is False
    assert watches.list_all(session) == []


def test_get_returns_none_when_absent(session):
    assert watches.get(session, "nope") is None


def test_claim_succeeds_once_per_key(session):
    assert sent.claim(session, "insights", "ecs_rollout", "42:success") is True
    assert sent.claim(session, "insights", "ecs_rollout", "42:success") is False


def test_claim_distinguishes_status_in_the_key(session):
    assert sent.claim(session, "insights", "ecs_rollout", "42:failed") is True
    assert sent.claim(session, "insights", "ecs_rollout", "42:success") is True


def test_claim_distinguishes_service_and_kind(session):
    assert sent.claim(session, "insights", "ci_run", "99") is True
    assert sent.claim(session, "api", "ci_run", "99") is True
    assert sent.claim(session, "insights", "ecs_rollout", "99") is True

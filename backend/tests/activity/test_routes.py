from datetime import UTC, datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

from maki.activity.cursor import encode_cursor
from maki.db.repository import DeployEventRepository
from maki.main import app
from maki.schemas import ActivityItem, ActivityResponse

repo = DeployEventRepository()


def _event(service="api", revision=1, sha="abc", platform="ecs", **overrides):
    base = {
        "service": service,
        "platform": platform,
        "revision": revision,
        "sha": sha,
        "image": f"repo:{sha}",
        "registered_at": datetime(2026, 5, 30, 12, 0, tzinfo=UTC),
        "committed_at": None,
        "finished_at": None,
        "author": None,
        "author_avatar_url": None,
        "message": None,
        "commit_url": None,
        "pr_url": None,
        "status": None,
        "is_rollback": False,
    }
    base.update(overrides)
    return base


def test_get_activity_endpoint():
    fake = ActivityResponse(
        items=[
            ActivityItem(id=1, service="newsfeed", platform="ecs", sha="abc", author="bailey")
        ],
        generated_at=datetime(2026, 5, 31, tzinfo=UTC),
        next_cursor="abc123",
    )
    with patch("maki.activity.routes.get_activity_service") as factory:
        factory.return_value.get_activity_page.return_value = fake
        client = TestClient(app)
        r = client.get("/api/activity")
    assert r.status_code == 200
    assert r.json()["items"][0]["service"] == "newsfeed"
    assert r.json()["items"][0]["author"] == "bailey"
    assert r.json()["next_cursor"] == "abc123"


def test_refresh_query_forces_recompute():
    fake = ActivityResponse(items=[], generated_at=datetime(2026, 5, 31, tzinfo=UTC))
    with patch("maki.activity.routes.get_activity_service") as factory:
        factory.return_value.get_activity_page.return_value = fake
        client = TestClient(app)
        client.get("/api/activity?refresh=1")
        factory.return_value.get_activity_page.assert_called_once_with(cursor=None, force=True)


def test_default_does_not_force():
    fake = ActivityResponse(items=[], generated_at=datetime(2026, 5, 31, tzinfo=UTC))
    with patch("maki.activity.routes.get_activity_service") as factory:
        factory.return_value.get_activity_page.return_value = fake
        client = TestClient(app)
        client.get("/api/activity")
        factory.return_value.get_activity_page.assert_called_once_with(cursor=None, force=False)


def test_cursor_query_decodes_and_pages():
    fake = ActivityResponse(items=[], generated_at=datetime(2026, 5, 31, tzinfo=UTC))
    cursor = encode_cursor(datetime(2026, 5, 31, 8, 0, tzinfo=UTC), 99)
    with patch("maki.activity.routes.get_activity_service") as factory:
        factory.return_value.get_activity_page.return_value = fake
        client = TestClient(app)
        r = client.get(f"/api/activity?cursor={cursor}")
    assert r.status_code == 200
    factory.return_value.get_activity_page.assert_called_once_with(
        cursor=(datetime(2026, 5, 31, 8, 0, tzinfo=UTC), 99), force=False
    )


def test_invalid_cursor_returns_422():
    with patch("maki.activity.routes.get_activity_service") as factory:
        client = TestClient(app)
        r = client.get("/api/activity?cursor=not-valid!!!")
    assert r.status_code == 422
    factory.return_value.get_activity_page.assert_not_called()


def test_cursor_ignored_when_around_supplied():
    fake = ActivityResponse(items=[], generated_at=datetime(2026, 5, 31, tzinfo=UTC))
    cursor = encode_cursor(datetime(2026, 5, 31, 8, 0, tzinfo=UTC), 1)
    with patch("maki.activity.routes.get_activity_service") as factory:
        factory.return_value.get_activity_around.return_value = fake
        client = TestClient(app)
        r = client.get(f"/api/activity?around=2026-05-31T14:30:00Z&cursor={cursor}")
    assert r.status_code == 200
    factory.return_value.get_activity_around.assert_called_once()
    factory.return_value.get_activity_page.assert_not_called()


def test_around_routes_to_windowed_query():
    fake = ActivityResponse(items=[], generated_at=datetime(2026, 5, 31, tzinfo=UTC))
    with patch("maki.activity.routes.get_activity_service") as factory:
        factory.return_value.get_activity_around.return_value = fake
        client = TestClient(app)
        r = client.get("/api/activity?around=2026-05-31T14:30:00Z&window=2")
    assert r.status_code == 200
    factory.return_value.get_activity_around.assert_called_once_with(
        datetime(2026, 5, 31, 14, 30, tzinfo=UTC), window_hours=2.0
    )
    # The latest-feed path is never taken when ``around`` is supplied.
    factory.return_value.get_activity.assert_not_called()


def test_around_defaults_window_to_six_hours():
    fake = ActivityResponse(items=[], generated_at=datetime(2026, 5, 31, tzinfo=UTC))
    with patch("maki.activity.routes.get_activity_service") as factory:
        factory.return_value.get_activity_around.return_value = fake
        client = TestClient(app)
        client.get("/api/activity?around=2026-05-31T14:30:00Z")
        factory.return_value.get_activity_around.assert_called_once_with(
            datetime(2026, 5, 31, 14, 30, tzinfo=UTC), window_hours=6.0
        )


def test_around_rejects_non_positive_window():
    with patch("maki.activity.routes.get_activity_service"):
        client = TestClient(app)
        r = client.get("/api/activity?around=2026-05-31T14:30:00Z&window=0")
    assert r.status_code == 422


def test_deploy_count_counts_ecs_events_at_or_after_since(session, session_factory):
    repo.upsert_many(
        session,
        [
            _event(revision=1, platform="ecs", registered_at=datetime(2026, 5, 31, tzinfo=UTC)),
            _event(revision=2, platform="ecs", registered_at=datetime(2026, 5, 29, tzinfo=UTC)),
            _event(revision=3, platform="amplify", registered_at=datetime(2026, 5, 31, tzinfo=UTC)),
        ],
    )
    session.flush()
    with patch("maki.activity.routes.get_session", session_factory):
        client = TestClient(app)
        r = client.get("/api/activity/deploy-count?since=2026-05-30T00:00:00Z")
    assert r.status_code == 200
    assert r.json()["count"] == 1


def test_deploy_count_requires_since():
    client = TestClient(app)
    r = client.get("/api/activity/deploy-count")
    assert r.status_code == 422

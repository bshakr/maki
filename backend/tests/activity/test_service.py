from datetime import UTC, datetime, timedelta

from maki.activity.cursor import decode_cursor
from maki.activity.service import ActivityService
from maki.db.repository import DeployEventRepository

repo = DeployEventRepository()

NOW = datetime(2026, 5, 31, 12, 0, tzinfo=UTC)


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


def _make(session_factory, **kwargs):
    return ActivityService(
        repository=repo,
        session_factory=session_factory,
        fresh_seconds=kwargs.pop("fresh_seconds", 0),
        stale_seconds=kwargs.pop("stale_seconds", 0),
        now=lambda: NOW,
        **kwargs,
    )


def test_chronological_feed_newest_first_across_services(session, session_factory):
    repo.upsert_many(
        session,
        [
            _event(service="old", revision=1, registered_at=datetime(2026, 5, 29, tzinfo=UTC)),
            _event(service="new", revision=1, registered_at=datetime(2026, 5, 31, tzinfo=UTC)),
            _event(service="mid", revision=1, registered_at=datetime(2026, 5, 30, tzinfo=UTC)),
        ],
    )
    session.flush()

    svc = _make(session_factory)
    resp = svc.get_activity()
    assert [i.service for i in resp.items] == ["new", "mid", "old"]
    assert resp.generated_at == NOW


def test_allows_multiple_events_per_service(session, session_factory):
    repo.upsert_many(
        session,
        [
            _event(service="api", revision=1, registered_at=datetime(2026, 5, 28, tzinfo=UTC)),
            _event(service="api", revision=2, registered_at=datetime(2026, 5, 30, tzinfo=UTC)),
        ],
    )
    session.flush()

    svc = _make(session_factory)
    resp = svc.get_activity()
    assert [i.service for i in resp.items] == ["api", "api"]  # both events, not collapsed


def test_caps_limit(session, session_factory):
    repo.upsert_many(
        session,
        [
            _event(service=f"s{i}", revision=1, registered_at=datetime(2026, 5, i, tzinfo=UTC))
            for i in range(1, 6)
        ],
    )
    session.flush()

    svc = _make(session_factory, limit=3)
    resp = svc.get_activity()
    assert len(resp.items) == 3


def test_carries_enriched_fields_and_maps_registered_at(session, session_factory):
    committed = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    registered = datetime(2026, 5, 31, tzinfo=UTC)
    repo.upsert_many(
        session,
        [
            _event(
                service="wfm-service",
                revision=1,
                sha="abc",
                platform="ecs",
                registered_at=registered,
                committed_at=committed,
                author="bailey",
                author_avatar_url="https://avatars.githubusercontent.com/u/1?v=4",
                message="fix tax calc",
                commit_url="https://gh/abc",
                pr_url="https://github.com/acme/platform/pull/4242",
            ),
        ],
    )
    session.flush()

    svc = _make(session_factory)
    item = svc.get_activity().items[0]
    assert item.service == "wfm-service"
    assert item.platform == "ecs"
    assert item.sha == "abc"
    assert item.deployed_at == registered  # finished_at is None here -> falls back to registered_at
    assert item.status is None  # status NULL in this row -> surfaced as None
    assert item.is_rollback is False
    assert item.author == "bailey"
    assert item.author_avatar_url == "https://avatars.githubusercontent.com/u/1?v=4"
    assert item.message == "fix tax calc"
    assert item.commit_url == "https://gh/abc"
    assert item.pr_url == "https://github.com/acme/platform/pull/4242"
    assert item.committed_at == committed


def test_surfaces_status_and_is_rollback(session, session_factory):
    repo.upsert_many(
        session,
        [
            _event(
                service="rolled-back",
                revision=1,
                status="success",
                is_rollback=True,
            ),
        ],
    )
    session.flush()

    item = _make(session_factory).get_activity().items[0]
    assert item.status == "success"
    assert item.is_rollback is True


def test_deployed_at_prefers_finished_at_over_registered_at(session, session_factory):
    registered = datetime(2026, 5, 31, 10, 0, tzinfo=UTC)
    finished = datetime(2026, 5, 31, 10, 14, tzinfo=UTC)  # went live 14m after registration
    repo.upsert_many(
        session,
        [_event(service="api", revision=1, registered_at=registered, finished_at=finished)],
    )
    session.flush()

    item = _make(session_factory).get_activity().items[0]
    assert item.deployed_at == finished  # go-live, not registration


def test_around_returns_events_within_window_both_sides(session, session_factory):
    target = datetime(2026, 5, 31, 14, 30, tzinfo=UTC)
    repo.upsert_many(
        session,
        [
            # 5h before -> outside a ±2h window
            _event(service="too-early", revision=1, registered_at=target - timedelta(hours=5)),
            # 1h before -> inside
            _event(service="before", revision=1, registered_at=target - timedelta(hours=1)),
            # 30m after -> inside
            _event(service="after", revision=1, registered_at=target + timedelta(minutes=30)),
            # 5h after -> outside
            _event(service="too-late", revision=1, registered_at=target + timedelta(hours=5)),
        ],
    )
    session.flush()

    svc = _make(session_factory)
    resp = svc.get_activity_around(target, window_hours=2)
    # Only the two in-window events, newest go-live first.
    assert [i.service for i in resp.items] == ["after", "before"]
    assert resp.generated_at == NOW


def test_around_uses_go_live_time_for_window(session, session_factory):
    target = datetime(2026, 5, 31, 14, 0, tzinfo=UTC)
    repo.upsert_many(
        session,
        [
            # registered far outside the window, but went live (finished_at) inside it -> included
            _event(
                service="late-rollout",
                revision=1,
                registered_at=target - timedelta(hours=10),
                finished_at=target + timedelta(minutes=15),
            ),
        ],
    )
    session.flush()

    svc = _make(session_factory)
    resp = svc.get_activity_around(target, window_hours=1)
    assert [i.service for i in resp.items] == ["late-rollout"]


def test_around_empty_window_returns_no_items(session, session_factory):
    repo.upsert_many(
        session,
        [_event(service="api", revision=1, registered_at=datetime(2026, 1, 1, tzinfo=UTC))],
    )
    session.flush()

    svc = _make(session_factory)
    resp = svc.get_activity_around(datetime(2026, 5, 31, 14, 0, tzinfo=UTC), window_hours=6)
    assert resp.items == []


def test_around_respects_explicit_max_window_events(session, session_factory):
    target = datetime(2026, 5, 31, 14, 0, tzinfo=UTC)
    repo.upsert_many(
        session,
        [
            _event(service=f"s{i}", revision=1, registered_at=target + timedelta(minutes=i))
            for i in range(10)
        ],
    )
    session.flush()

    svc = _make(session_factory, max_window_events=4)
    resp = svc.get_activity_around(target, window_hours=6)
    assert len(resp.items) == 4  # explicit cap, not the default feed's 50


def test_around_is_not_cached(session, session_factory):
    repo.upsert_many(session, [_event()])
    session.flush()
    svc = _make(session_factory, fresh_seconds=60, stale_seconds=300)
    target = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    first = svc.get_activity_around(target, window_hours=24)
    second = svc.get_activity_around(target, window_hours=24)
    assert first is not second  # point-in-time query reads fresh each call


def test_first_page_returns_next_cursor_when_more_exist(session, session_factory):
    repo.upsert_many(
        session,
        [
            _event(service=f"s{i}", revision=1, registered_at=datetime(2026, 5, i, tzinfo=UTC))
            for i in range(1, 6)
        ],
    )
    session.flush()

    svc = _make(session_factory, limit=2)
    resp = svc.get_activity_page()
    assert [i.service for i in resp.items] == ["s5", "s4"]
    assert resp.next_cursor is not None  # a full page -> there may be more
    deployed_at, _id = decode_cursor(resp.next_cursor)
    assert deployed_at == datetime(2026, 5, 4, tzinfo=UTC)  # last row's go-live


def test_cursor_returns_the_next_slice(session, session_factory):
    repo.upsert_many(
        session,
        [
            _event(service=f"s{i}", revision=1, registered_at=datetime(2026, 5, i, tzinfo=UTC))
            for i in range(1, 6)
        ],
    )
    session.flush()

    svc = _make(session_factory, limit=2)
    page1 = svc.get_activity_page()
    page2 = svc.get_activity_page(cursor=decode_cursor(page1.next_cursor))
    assert [i.service for i in page2.items] == ["s3", "s2"]


def test_next_cursor_is_null_at_the_end(session, session_factory):
    repo.upsert_many(
        session,
        [
            _event(service=f"s{i}", revision=1, registered_at=datetime(2026, 5, i, tzinfo=UTC))
            for i in range(1, 4)  # 3 events, page size 2 -> page 2 is the short tail
        ],
    )
    session.flush()

    svc = _make(session_factory, limit=2)
    page1 = svc.get_activity_page()
    page2 = svc.get_activity_page(cursor=decode_cursor(page1.next_cursor))
    assert [i.service for i in page2.items] == ["s1"]
    assert page2.next_cursor is None  # short page -> tail of the feed


def test_full_final_page_yields_empty_next_page(session, session_factory):
    # Exactly `limit` rows: page 1 is full so next_cursor is non-null, but the next page is empty.
    repo.upsert_many(
        session,
        [
            _event(service=f"s{i}", revision=1, registered_at=datetime(2026, 5, i, tzinfo=UTC))
            for i in range(1, 3)
        ],
    )
    session.flush()

    svc = _make(session_factory, limit=2)
    page1 = svc.get_activity_page()
    assert page1.next_cursor is not None
    page2 = svc.get_activity_page(cursor=decode_cursor(page1.next_cursor))
    assert page2.items == []
    assert page2.next_cursor is None


def test_paged_feed_walks_every_event_without_overlap(session, session_factory):
    repo.upsert_many(
        session,
        [
            _event(service=f"s{i}", revision=1, registered_at=datetime(2026, 5, i, tzinfo=UTC))
            for i in range(1, 6)
        ],
    )
    session.flush()

    svc = _make(session_factory, limit=2)
    seen: list[str] = []
    resp = svc.get_activity_page()
    seen.extend(i.service for i in resp.items)
    while resp.next_cursor:
        resp = svc.get_activity_page(cursor=decode_cursor(resp.next_cursor))
        seen.extend(i.service for i in resp.items)

    assert seen == ["s5", "s4", "s3", "s2", "s1"]
    assert len(seen) == len(set(seen))


def test_first_page_is_cached_but_cursor_pages_read_fresh(session, session_factory):
    repo.upsert_many(session, [_event(), _event(revision=2, sha="def")])
    session.flush()
    svc = _make(session_factory, fresh_seconds=60, stale_seconds=300, limit=1)

    # Page 1 (no cursor) shares the SWR cache entry with get_activity.
    first = svc.get_activity_page()
    assert first is svc.get_activity_page()
    assert first is svc.get_activity()

    # Cursor pages bypass the cache (fresh read each call), like get_activity_around.
    cursor = decode_cursor(first.next_cursor)
    assert svc.get_activity_page(cursor=cursor) is not svc.get_activity_page(cursor=cursor)


def test_serves_cached_within_fresh_window(session, session_factory):
    repo.upsert_many(session, [_event()])
    session.flush()
    svc = _make(session_factory, fresh_seconds=60, stale_seconds=300)
    first = svc.get_activity()
    second = svc.get_activity()
    assert first is second


def test_force_recomputes_activity(session, session_factory):
    repo.upsert_many(session, [_event()])
    session.flush()
    svc = _make(session_factory, fresh_seconds=60, stale_seconds=300)
    first = svc.get_activity()
    second = svc.get_activity(force=True)
    assert first is not second

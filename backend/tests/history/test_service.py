from datetime import UTC, datetime

from maki.activity.cursor import decode_cursor
from maki.db.repository import DeployEventRepository
from maki.history.service import HistoryService

repo = DeployEventRepository()

# Fixed clock so generated_at is deterministic.
NOW = datetime(2026, 5, 31, 12, 0, tzinfo=UTC)


def _event(service="newsfeed", revision=1, sha="abc", **overrides):
    base = {
        "service": service,
        "platform": "ecs",
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
    return HistoryService(
        repository=repo,
        session_factory=session_factory,
        fresh_seconds=kwargs.pop("fresh_seconds", 0),
        stale_seconds=kwargs.pop("stale_seconds", 0),
        now=lambda: NOW,
        **kwargs,
    )


def test_maps_stored_events_to_deploy_records(session, session_factory):
    repo.upsert_many(
        session,
        [
            _event(
                revision=7,
                sha="abc",
                registered_at=datetime(2026, 5, 30, 12, 0, tzinfo=UTC),
                committed_at=datetime(2026, 5, 30, 9, 15, tzinfo=UTC),
                finished_at=datetime(2026, 5, 30, 13, 0, tzinfo=UTC),
                author="bailey",
                author_avatar_url="https://avatars.githubusercontent.com/u/1?v=4",
                message="msg abc",
                commit_url="https://gh/abc",
                pr_url="https://github.com/acme/platform/pull/1",
            ),
            _event(revision=6, sha="def", registered_at=datetime(2026, 5, 29, 12, 0, tzinfo=UTC)),
        ],
    )
    session.flush()

    svc = _make(session_factory)
    resp = svc.get_deployments("newsfeed")

    assert resp.service == "newsfeed"
    assert resp.generated_at == NOW
    assert [d.sha for d in resp.deployments] == ["abc", "def"]  # newest first
    top = resp.deployments[0]
    assert top.revision == 7
    assert top.image == "repo:abc"
    assert top.registered_at == datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    assert top.committed_at == datetime(2026, 5, 30, 9, 15, tzinfo=UTC)
    assert top.finished_at == datetime(2026, 5, 30, 13, 0, tzinfo=UTC)
    assert top.author == "bailey"
    assert top.author_avatar_url == "https://avatars.githubusercontent.com/u/1?v=4"
    assert top.message == "msg abc"
    assert top.commit_url == "https://gh/abc"
    assert top.pr_url == "https://github.com/acme/platform/pull/1"


def test_applies_limit_to_newest_events(session, session_factory):
    repo.upsert_many(
        session,
        [
            _event(revision=i, sha=f"s{i}", registered_at=datetime(2026, 5, i, tzinfo=UTC))
            for i in range(1, 6)
        ],
    )
    session.flush()

    svc = _make(session_factory, limit=2)
    resp = svc.get_deployments("newsfeed")
    assert [d.revision for d in resp.deployments] == [5, 4]


def test_scopes_to_service(session, session_factory):
    repo.upsert_many(
        session,
        [_event(service="newsfeed", revision=1), _event(service="workforce", revision=1)],
    )
    session.flush()

    svc = _make(session_factory)
    resp = svc.get_deployments("newsfeed")
    assert resp.deployments != []
    assert all(d.sha == "abc" for d in resp.deployments)


def test_unknown_service_returns_empty(session, session_factory):
    svc = _make(session_factory)
    resp = svc.get_deployments("ghost")
    assert resp.deployments == []


def test_serves_cached_within_fresh_window(session, session_factory):
    repo.upsert_many(session, [_event(revision=1)])
    session.flush()
    svc = _make(session_factory, fresh_seconds=60, stale_seconds=300)
    first = svc.get_deployments("newsfeed")
    second = svc.get_deployments("newsfeed")
    assert first is second  # served from cache, not recomputed


def test_force_recomputes_deployments(session, session_factory):
    repo.upsert_many(session, [_event(revision=1)])
    session.flush()
    svc = _make(session_factory, fresh_seconds=60, stale_seconds=300)
    first = svc.get_deployments("newsfeed")
    second = svc.get_deployments("newsfeed", force=True)
    assert first is not second  # forced recompute returns a fresh object


def test_get_deployments_since_filters_by_cutoff(session, session_factory):
    repo.upsert_many(
        session,
        [
            _event(revision=2, sha="new", registered_at=datetime(2026, 5, 30, tzinfo=UTC)),
            _event(revision=1, sha="old", registered_at=datetime(2026, 1, 1, tzinfo=UTC)),
        ],
    )
    session.flush()

    svc = _make(session_factory)
    out = svc.get_deployments_since("newsfeed", datetime(2026, 5, 1, tzinfo=UTC))
    assert [r.sha for r in out] == ["new"]


def test_get_deployments_since_maps_all_fields(session, session_factory):
    committed = datetime(2026, 5, 30, 9, 0, tzinfo=UTC)
    repo.upsert_many(
        session,
        [
            _event(
                revision=7,
                sha="abc",
                registered_at=datetime(2026, 5, 30, 12, 0, tzinfo=UTC),
                committed_at=committed,
                author="bailey",
            ),
        ],
    )
    session.flush()

    svc = _make(session_factory)
    out = svc.get_deployments_since("newsfeed", datetime(2026, 5, 1, tzinfo=UTC))
    assert out[0].sha == "abc"
    assert out[0].author == "bailey"
    assert out[0].committed_at == committed


def test_get_deployments_since_caches_by_cutoff_date(session, session_factory):
    repo.upsert_many(session, [_event(revision=7)])
    session.flush()
    svc = _make(session_factory, fresh_seconds=60, stale_seconds=300)
    # Two calls same day, different times -> share one cache entry (same object returned).
    first = svc.get_deployments_since("newsfeed", datetime(2026, 5, 31, 8, 0, tzinfo=UTC))
    second = svc.get_deployments_since("newsfeed", datetime(2026, 5, 31, 20, 0, tzinfo=UTC))
    assert first is second


def test_surfaces_status_and_is_rollback(session, session_factory):
    repo.upsert_many(
        session,
        [_event(revision=1, status="success", is_rollback=True)],
    )
    session.flush()

    rec = _make(session_factory).get_deployments("newsfeed").deployments[0]
    assert rec.status == "success"
    assert rec.is_rollback is True


def test_get_deploy_maps_single_event(session, session_factory):
    repo.upsert_many(
        session,
        [
            _event(
                revision=7,
                sha="af0968fabc123",
                committed_at=datetime(2026, 5, 30, 9, 0, tzinfo=UTC),
                author="bailey",
                status="success",
                is_rollback=True,
            ),
        ],
    )
    session.flush()

    rec = _make(session_factory).get_deploy("newsfeed", "af0968f")
    assert rec is not None
    assert rec.sha == "af0968fabc123"
    assert rec.revision == 7
    assert rec.author == "bailey"
    assert rec.committed_at == datetime(2026, 5, 30, 9, 0, tzinfo=UTC)
    assert rec.status == "success"
    assert rec.is_rollback is True
    assert rec.id is not None


def test_get_deploy_returns_none_when_not_found(session, session_factory):
    repo.upsert_many(session, [_event(revision=1, sha="af0968fabc123")])
    session.flush()

    assert _make(session_factory).get_deploy("newsfeed", "deadbee") is None


def test_first_page_returns_next_cursor_when_more_exist(session, session_factory):
    repo.upsert_many(
        session,
        [
            _event(revision=i, sha=f"s{i}", registered_at=datetime(2026, 5, i, tzinfo=UTC))
            for i in range(1, 6)
        ],
    )
    session.flush()

    svc = _make(session_factory, limit=2)
    resp = svc.get_deployments("newsfeed")
    assert [d.sha for d in resp.deployments] == ["s5", "s4"]  # newest registered first
    assert resp.next_cursor is not None  # full page -> there may be more
    at, _id = decode_cursor(resp.next_cursor)
    assert at == datetime(2026, 5, 4, tzinfo=UTC)  # last row's registered_at


def test_cursor_returns_the_next_slice(session, session_factory):
    repo.upsert_many(
        session,
        [
            _event(revision=i, sha=f"s{i}", registered_at=datetime(2026, 5, i, tzinfo=UTC))
            for i in range(1, 6)
        ],
    )
    session.flush()

    svc = _make(session_factory, limit=2)
    page1 = svc.get_deployments("newsfeed")
    page2 = svc.get_deployments_page("newsfeed", cursor=decode_cursor(page1.next_cursor))
    assert [d.sha for d in page2.deployments] == ["s3", "s2"]


def test_next_cursor_is_null_at_the_end(session, session_factory):
    repo.upsert_many(
        session,
        [
            _event(revision=i, sha=f"s{i}", registered_at=datetime(2026, 5, i, tzinfo=UTC))
            for i in range(1, 4)  # 3 events, page size 2 -> page 2 is the short tail
        ],
    )
    session.flush()

    svc = _make(session_factory, limit=2)
    page1 = svc.get_deployments("newsfeed")
    page2 = svc.get_deployments_page("newsfeed", cursor=decode_cursor(page1.next_cursor))
    assert [d.sha for d in page2.deployments] == ["s1"]
    assert page2.next_cursor is None  # short page -> tail


def test_paged_history_walks_every_event_without_overlap(session, session_factory):
    repo.upsert_many(
        session,
        [
            _event(revision=i, sha=f"s{i}", registered_at=datetime(2026, 5, i, tzinfo=UTC))
            for i in range(1, 6)
        ],
    )
    session.flush()

    svc = _make(session_factory, limit=2)
    seen: list[str] = []
    resp = svc.get_deployments("newsfeed")
    seen.extend(d.sha for d in resp.deployments)
    while resp.next_cursor:
        resp = svc.get_deployments_page("newsfeed", cursor=decode_cursor(resp.next_cursor))
        seen.extend(d.sha for d in resp.deployments)

    assert seen == ["s5", "s4", "s3", "s2", "s1"]
    assert len(seen) == len(set(seen))


def test_first_page_is_cached_but_cursor_pages_read_fresh(session, session_factory):
    repo.upsert_many(
        session,
        [
            _event(revision=1, sha="a", registered_at=datetime(2026, 5, 2, tzinfo=UTC)),
            _event(revision=2, sha="b", registered_at=datetime(2026, 5, 1, tzinfo=UTC)),
        ],
    )
    session.flush()
    svc = _make(session_factory, fresh_seconds=60, stale_seconds=300, limit=1)

    # Page 1 (no cursor) shares the SWR cache entry with get_deployments.
    first = svc.get_deployments_page("newsfeed")
    assert first is svc.get_deployments_page("newsfeed")
    assert first is svc.get_deployments("newsfeed")

    # Cursor pages bypass the cache (fresh read each call).
    cursor = decode_cursor(first.next_cursor)
    assert svc.get_deployments_page("newsfeed", cursor=cursor) is not svc.get_deployments_page(
        "newsfeed", cursor=cursor
    )

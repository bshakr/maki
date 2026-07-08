from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from maki.db.models import DeployEvent
from maki.db.repository import DeployEventRepository

repo = DeployEventRepository()


def _event(service="api", revision=1, sha="abc", **overrides):
    base = {
        "service": service,
        "platform": "ecs",
        "revision": revision,
        "sha": sha,
        "image": f"repo:{sha}",
        "registered_at": datetime(2026, 5, 30, 12, 0, tzinfo=UTC),
        "committed_at": None,
        "author": None,
        "message": None,
        "commit_url": None,
        "pr_url": None,
        "status": None,
        "is_rollback": False,
    }
    base.update(overrides)
    return base


def _count(session) -> int:
    return session.scalar(select(func.count()).select_from(DeployEvent))


def test_upsert_many_inserts(session):
    repo.upsert_many(session, [_event(revision=1), _event(revision=2)])
    session.flush()
    assert _count(session) == 2


def test_reupsert_same_key_updates_not_duplicates(session):
    repo.upsert_many(session, [_event(revision=5, sha="old", author="alice")])
    session.flush()
    assert _count(session) == 1

    repo.upsert_many(session, [_event(revision=5, sha="new", author="bob")])
    session.flush()

    assert _count(session) == 1  # row count stable
    row = session.scalars(select(DeployEvent).where(DeployEvent.revision == 5)).one()
    assert row.sha == "new"  # fields updated
    assert row.author == "bob"


def test_list_for_service_since_filters_by_registered_at(session):
    old = datetime(2026, 1, 1, tzinfo=UTC)
    recent = datetime(2026, 5, 30, tzinfo=UTC)
    repo.upsert_many(
        session,
        [
            _event(service="api", revision=1, registered_at=old),
            _event(service="api", revision=2, registered_at=recent),
        ],
    )
    session.flush()

    cutoff = recent - timedelta(days=1)
    results = repo.list_for_service_since(session, "api", cutoff)
    assert [e.revision for e in results] == [2]


def test_list_for_service_since_orders_newest_first(session):
    repo.upsert_many(
        session,
        [
            _event(service="api", revision=1, registered_at=datetime(2026, 5, 1, tzinfo=UTC)),
            _event(service="api", revision=2, registered_at=datetime(2026, 5, 20, tzinfo=UTC)),
            _event(service="api", revision=3, registered_at=datetime(2026, 5, 10, tzinfo=UTC)),
        ],
    )
    session.flush()

    results = repo.list_for_service_since(session, "api", datetime(2026, 1, 1, tzinfo=UTC))
    assert [e.revision for e in results] == [2, 3, 1]


def test_list_for_service_since_scopes_to_service(session):
    repo.upsert_many(
        session,
        [
            _event(service="api", revision=1),
            _event(service="worker", revision=1),
        ],
    )
    session.flush()

    results = repo.list_for_service_since(session, "api", datetime(2026, 1, 1, tzinfo=UTC))
    assert {e.service for e in results} == {"api"}


def test_list_for_service_orders_newest_first(session):
    repo.upsert_many(
        session,
        [
            _event(service="api", revision=1, registered_at=datetime(2026, 5, 1, tzinfo=UTC)),
            _event(service="api", revision=2, registered_at=datetime(2026, 5, 20, tzinfo=UTC)),
            _event(service="api", revision=3, registered_at=datetime(2026, 5, 10, tzinfo=UTC)),
        ],
    )
    session.flush()

    results = repo.list_for_service(session, "api")
    assert [e.revision for e in results] == [2, 3, 1]


def test_list_for_service_applies_limit(session):
    repo.upsert_many(
        session,
        [
            _event(service="api", revision=i, registered_at=datetime(2026, 5, i, tzinfo=UTC))
            for i in range(1, 6)
        ],
    )
    session.flush()

    results = repo.list_for_service(session, "api", limit=2)
    assert [e.revision for e in results] == [5, 4]  # newest two only


def test_list_for_service_scopes_to_service(session):
    repo.upsert_many(
        session,
        [
            _event(service="api", revision=1),
            _event(service="worker", revision=1),
        ],
    )
    session.flush()

    results = repo.list_for_service(session, "api")
    assert {e.service for e in results} == {"api"}


def test_list_page_for_service_first_page_orders_newest_registered_first(session):
    repo.upsert_many(
        session,
        [
            _event(service="api", revision=i, registered_at=datetime(2026, 5, i, tzinfo=UTC))
            for i in range(1, 4)
        ],
    )
    session.flush()

    results = repo.list_page_for_service(session, "api", limit=10)
    assert [e.revision for e in results] == [3, 2, 1]


def test_list_page_for_service_scopes_to_service(session):
    repo.upsert_many(
        session,
        [_event(service="api", revision=1), _event(service="worker", revision=1)],
    )
    session.flush()

    results = repo.list_page_for_service(session, "api", limit=10)
    assert {e.service for e in results} == {"api"}


def test_list_page_for_service_cursor_returns_next_slice(session):
    repo.upsert_many(
        session,
        [
            _event(
                service="api",
                revision=i,
                sha=f"s{i}",
                registered_at=datetime(2026, 5, i, tzinfo=UTC),
            )
            for i in range(1, 6)
        ],
    )
    session.flush()

    first = repo.list_page_for_service(session, "api", limit=2)
    assert [e.sha for e in first] == ["s5", "s4"]
    cursor = (first[-1].registered_at, first[-1].id)
    second = repo.list_page_for_service(session, "api", limit=2, before=cursor)
    assert [e.sha for e in second] == ["s3", "s2"]


def test_list_page_for_service_tiebreaks_on_id_for_equal_registered_at(session):
    same = datetime(2026, 5, 10, 10, 0, tzinfo=UTC)
    repo.upsert_many(
        session,
        [
            _event(service="api", revision=1, sha="s1", registered_at=same),
            _event(service="api", revision=2, sha="s2", registered_at=same),
        ],
    )
    session.flush()

    rows = repo.list_page_for_service(session, "api", limit=10)
    # Same registered_at -> ordered by id DESC (the later-inserted row first).
    assert [e.id for e in rows] == sorted((e.id for e in rows), reverse=True)
    page1 = repo.list_page_for_service(session, "api", limit=1)
    cursor = (page1[-1].registered_at, page1[-1].id)
    page2 = repo.list_page_for_service(session, "api", limit=1, before=cursor)
    assert page1[0].id != page2[0].id  # no overlap across the tie


def test_list_page_for_service_walks_to_the_end_without_overlap(session):
    repo.upsert_many(
        session,
        [
            _event(
                service="api",
                revision=i,
                sha=f"s{i}",
                registered_at=datetime(2026, 5, i, tzinfo=UTC),
            )
            for i in range(1, 6)
        ],
    )
    session.flush()

    seen: list[str] = []
    cursor = None
    while True:
        page = repo.list_page_for_service(session, "api", limit=2, before=cursor)
        if not page:
            break
        seen.extend(e.sha for e in page)
        if len(page) < 2:
            break
        cursor = (page[-1].registered_at, page[-1].id)
    assert seen == ["s5", "s4", "s3", "s2", "s1"]
    assert len(seen) == len(set(seen))


def test_list_page_first_page_orders_newest_first(session):
    repo.upsert_many(
        session,
        [
            _event(service="api", revision=1, registered_at=datetime(2026, 5, 1, tzinfo=UTC)),
            _event(service="worker", revision=1, registered_at=datetime(2026, 5, 20, tzinfo=UTC)),
            _event(service="api", revision=2, registered_at=datetime(2026, 5, 10, tzinfo=UTC)),
        ],
    )
    session.flush()

    results = repo.list_page(session, limit=10)
    assert [(e.service, e.revision) for e in results] == [
        ("worker", 1),
        ("api", 2),
        ("api", 1),
    ]


def test_list_page_cursor_returns_next_slice(session):
    repo.upsert_many(
        session,
        [
            _event(service=f"s{i}", revision=1, registered_at=datetime(2026, 5, i, tzinfo=UTC))
            for i in range(1, 6)
        ],
    )
    session.flush()

    first = repo.list_page(session, limit=2)
    assert [e.service for e in first] == ["s5", "s4"]

    last = first[-1]
    cursor = (last.finished_at or last.registered_at, last.id)
    second = repo.list_page(session, limit=2, before=cursor)
    # Strictly after the cursor: the next two older events, no overlap with the first page.
    assert [e.service for e in second] == ["s3", "s2"]


def test_list_page_walks_to_the_end_without_overlap(session):
    repo.upsert_many(
        session,
        [
            _event(service=f"s{i}", revision=1, registered_at=datetime(2026, 5, i, tzinfo=UTC))
            for i in range(1, 6)
        ],
    )
    session.flush()

    seen = []
    cursor = None
    while True:
        page = repo.list_page(session, limit=2, before=cursor)
        if not page:
            break
        seen.extend(e.service for e in page)
        last = page[-1]
        cursor = (last.finished_at or last.registered_at, last.id)
        if len(page) < 2:
            break

    assert seen == ["s5", "s4", "s3", "s2", "s1"]
    assert len(seen) == len(set(seen))  # no duplicates across pages


def test_list_page_tiebreaks_on_id_for_equal_go_live(session):
    same = datetime(2026, 5, 10, 10, 0, tzinfo=UTC)
    repo.upsert_many(
        session,
        [
            _event(service="a", revision=1, registered_at=same),
            _event(service="b", revision=1, registered_at=same),
            _event(service="c", revision=1, registered_at=same),
        ],
    )
    session.flush()

    rows = repo.list_page(session, limit=10)
    # All share a go-live instant -> ordered by id DESC (latest-inserted first), deterministically.
    ids = [e.id for e in rows]
    assert ids == sorted(ids, reverse=True)

    # Paging through that equal-go-live cluster must not skip or repeat any row.
    page1 = repo.list_page(session, limit=2)
    cursor = (page1[-1].finished_at or page1[-1].registered_at, page1[-1].id)
    page2 = repo.list_page(session, limit=2, before=cursor)
    assert [e.id for e in page1 + page2] == ids


def test_list_page_uses_go_live_not_registration_for_ordering(session):
    repo.upsert_many(
        session,
        [
            _event(
                service="a",
                revision=1,
                registered_at=datetime(2026, 5, 10, 10, 0, tzinfo=UTC),
                finished_at=datetime(2026, 5, 10, 10, 30, tzinfo=UTC),
            ),
            _event(
                service="b",
                revision=1,
                registered_at=datetime(2026, 5, 10, 10, 5, tzinfo=UTC),
                finished_at=datetime(2026, 5, 10, 10, 6, tzinfo=UTC),
            ),
        ],
    )
    session.flush()

    assert [e.service for e in repo.list_page(session)] == ["a", "b"]


def test_list_services_distinct_and_sorted(session):
    repo.upsert_many(
        session,
        [
            _event(service="worker", revision=1),
            _event(service="api", revision=1),
            _event(service="worker", revision=2),
            _event(service="zebra", revision=1),
        ],
    )
    session.flush()

    assert repo.list_services(session) == ["api", "worker", "zebra"]


def test_get_by_service_and_sha_matches_on_prefix(session):
    repo.upsert_many(
        session,
        [_event(service="api", revision=1, sha="af0968fabc123")],
    )
    session.flush()

    found = repo.get_by_service_and_sha(session, "api", "af0968f")
    assert found is not None
    assert found.sha == "af0968fabc123"


def test_get_by_service_and_sha_returns_none_when_no_match(session):
    repo.upsert_many(session, [_event(service="api", revision=1, sha="af0968fabc123")])
    session.flush()

    assert repo.get_by_service_and_sha(session, "api", "deadbee") is None
    # Right sha prefix, wrong service -> no match (scoped to service).
    assert repo.get_by_service_and_sha(session, "worker", "af0968f") is None


def test_get_by_service_and_sha_picks_newest_on_prefix_collision(session):
    # Two full shas sharing the 7-char short prefix; newest registered_at must win.
    repo.upsert_many(
        session,
        [
            _event(
                service="api",
                revision=1,
                sha="af0968fOLD0001",
                registered_at=datetime(2026, 5, 1, tzinfo=UTC),
            ),
            _event(
                service="api",
                revision=2,
                sha="af0968fNEW0002",
                registered_at=datetime(2026, 5, 20, tzinfo=UTC),
            ),
        ],
    )
    session.flush()

    found = repo.get_by_service_and_sha(session, "api", "af0968f")
    assert found is not None
    assert found.sha == "af0968fNEW0002"  # newest registered_at wins


def test_get_by_service_and_sha_treats_wildcards_literally(session):
    # A prefix containing a LIKE wildcard must not match an arbitrary sha.
    repo.upsert_many(session, [_event(service="api", revision=1, sha="af0968fabc123")])
    session.flush()

    assert repo.get_by_service_and_sha(session, "api", "%") is None
    assert repo.get_by_service_and_sha(session, "api", "af0968_") is None


def test_upsert_many_empty_is_noop(session):
    repo.upsert_many(session, [])
    session.flush()
    assert _count(session) == 0

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from maki.db.repository import DeployEventRepository
from maki.history.service import HistoryService
from maki.metrics.service import MetricsService
from maki.schemas import DeployedService, ServicesResponse

repo = DeployEventRepository()

# Fixed clock: tests pin "now" so trend buckets and cutoff are deterministic.
NOW = datetime(2026, 5, 31, 12, 0, tzinfo=UTC)


def _inventory(services):
    inv = MagicMock()
    inv.get_inventory.return_value = ServicesResponse(services=services, generated_at=NOW)
    return inv


def _ecs(name):
    return DeployedService(name=name, platform="ecs")


def _amplify(name):
    return DeployedService(name=name, platform="amplify")


def _event(
    service,
    revision,
    registered_at,
    committed_at=None,
    finished_at=None,
    status=None,
    is_rollback=False,
    author=None,
):
    return {
        "service": service,
        "platform": "ecs",
        "revision": revision,
        "sha": f"{service}-{revision}",
        "image": None,
        "registered_at": registered_at,
        "committed_at": committed_at,
        "finished_at": finished_at,
        "author": author,
        "author_avatar_url": None,
        "message": None,
        "commit_url": None,
        "pr_url": None,
        "status": status,
        "is_rollback": is_rollback,
    }


def _history(session_factory):
    """A real store-backed HistoryService against the seeded test session."""
    return HistoryService(
        repository=repo,
        session_factory=session_factory,
        fresh_seconds=0,
        stale_seconds=0,
        now=lambda: NOW,
    )


def _make(inventory, history, range_days=30, service="all"):
    svc = MetricsService(
        inventory=inventory,
        history=history,
        fresh_seconds=0,
        stale_seconds=0,
        now=lambda: NOW,
    )
    return svc.get_metrics(range_days, service)


def test_aggregates_fleet_metrics_and_zero_filled_trend(session, session_factory):
    inv = _inventory([_ecs("inventory"), _ecs("workforce"), _amplify("web-app")])
    repo.upsert_many(
        session,
        [
            # committed 07:00 -> registered 10:00 -> finished 10:00; lead (committed->live) = 3h
            _event(
                "inventory",
                1,
                datetime(2026, 5, 30, 10, 0, tzinfo=UTC),
                datetime(2026, 5, 30, 7, 0, tzinfo=UTC),
                datetime(2026, 5, 30, 10, 0, tzinfo=UTC),
            ),
            # committed 09:00 -> finished 10:00; lead = 1h
            _event(
                "inventory",
                2,
                datetime(2026, 5, 28, 10, 0, tzinfo=UTC),
                datetime(2026, 5, 28, 9, 0, tzinfo=UTC),
                datetime(2026, 5, 28, 10, 0, tzinfo=UTC),
            ),
            # committed 11:00 -> finished 12:00; lead = 1h
            _event(
                "workforce",
                1,
                datetime(2026, 5, 30, 12, 0, tzinfo=UTC),
                datetime(2026, 5, 30, 11, 0, tzinfo=UTC),
                datetime(2026, 5, 30, 12, 0, tzinfo=UTC),
            ),
        ],
    )
    session.flush()

    resp = _make(inv, _history(session_factory), range_days=30, service="all")

    assert resp.range_days == 30
    assert resp.service == "all"
    assert resp.deploy_count == 3
    assert resp.deploys_per_day == round(3 / 30, 2)
    # committed->live lead times: 3h=10800, 1h=3600, 1h=3600 -> median 3600
    assert resp.lead_time_median_seconds == 3600
    # amplify excluded from services filter list
    assert resp.services == ["inventory", "workforce"]
    # trend spans cutoff.date()..now.date() inclusive == range_days + 1 days
    assert len(resp.trend) == 31
    assert resp.trend[0].date == "2026-05-01"
    assert resp.trend[-1].date == "2026-05-31"
    counts = {b.date: b.count for b in resp.trend}
    assert counts["2026-05-30"] == 2
    assert counts["2026-05-28"] == 1
    assert counts["2026-05-29"] == 0


def test_excludes_deploys_before_cutoff(session, session_factory):
    inv = _inventory([_ecs("inventory")])
    repo.upsert_many(
        session,
        [
            _event("inventory", 1, datetime(2026, 5, 30, 10, 0, tzinfo=UTC)),  # within 7d
            _event("inventory", 2, datetime(2026, 5, 20, 10, 0, tzinfo=UTC)),  # outside 7d
        ],
    )
    session.flush()
    resp = _make(inv, _history(session_factory), range_days=7, service="all")
    assert resp.deploy_count == 1
    assert len(resp.trend) == 8


def test_lead_time_skips_negative_and_missing(session, session_factory):
    inv = _inventory([_ecs("inventory")])
    repo.upsert_many(
        session,
        [
            # committed 09:00 -> finished 10:00; valid 1h lead
            _event(
                "inventory",
                1,
                datetime(2026, 5, 30, 10, 0, tzinfo=UTC),
                datetime(2026, 5, 30, 9, 0, tzinfo=UTC),
                datetime(2026, 5, 30, 10, 0, tzinfo=UTC),
            ),
            # no committed_at -> excluded from lead time
            _event("inventory", 2, datetime(2026, 5, 30, 8, 0, tzinfo=UTC)),
            # finished_at < committed_at -> excluded
            _event(
                "inventory",
                3,
                datetime(2026, 5, 30, 7, 0, tzinfo=UTC),
                datetime(2026, 5, 30, 9, 0, tzinfo=UTC),
                datetime(2026, 5, 30, 8, 0, tzinfo=UTC),
            ),
            # committed present but no finished_at -> excluded from lead time
            _event(
                "inventory",
                4,
                datetime(2026, 5, 30, 6, 0, tzinfo=UTC),
                datetime(2026, 5, 30, 5, 0, tzinfo=UTC),
            ),
        ],
    )
    session.flush()
    resp = _make(inv, _history(session_factory), range_days=30, service="all")
    assert resp.deploy_count == 4
    assert resp.lead_time_median_seconds == 3600  # only the one valid 1h lead time


def test_no_valid_lead_times_returns_none(session, session_factory):
    inv = _inventory([_ecs("inventory")])
    repo.upsert_many(session, [_event("inventory", 1, datetime(2026, 5, 30, 10, 0, tzinfo=UTC))])
    session.flush()
    resp = _make(inv, _history(session_factory), range_days=30, service="all")
    assert resp.deploy_count == 1
    assert resp.lead_time_median_seconds is None
    assert resp.lead_time_p90_seconds is None
    assert resp.ci_median_seconds is None
    assert resp.rollout_median_seconds is None


def test_committed_to_live_lead_p90_and_ci_rollout_breakdown(session, session_factory):
    # Three deploys with distinct committed/registered/finished triplets so each aggregate is
    # independently verifiable.
    inv = _inventory([_ecs("inventory")])
    repo.upsert_many(
        session,
        [
            # committed 06:00 -> registered 07:00 (ci 1h) -> finished 08:00 (rollout 1h); lead 2h
            _event(
                "inventory",
                1,
                datetime(2026, 5, 30, 7, 0, tzinfo=UTC),
                datetime(2026, 5, 30, 6, 0, tzinfo=UTC),
                datetime(2026, 5, 30, 8, 0, tzinfo=UTC),
            ),
            # committed 06:00 -> registered 08:00 (ci 2h) -> finished 10:00 (rollout 2h); lead 4h
            _event(
                "inventory",
                2,
                datetime(2026, 5, 29, 8, 0, tzinfo=UTC),
                datetime(2026, 5, 29, 6, 0, tzinfo=UTC),
                datetime(2026, 5, 29, 10, 0, tzinfo=UTC),
            ),
            # committed 06:00 -> registered 09:00 (ci 3h) -> finished 12:00 (rollout 3h); lead 6h
            _event(
                "inventory",
                3,
                datetime(2026, 5, 28, 9, 0, tzinfo=UTC),
                datetime(2026, 5, 28, 6, 0, tzinfo=UTC),
                datetime(2026, 5, 28, 12, 0, tzinfo=UTC),
            ),
        ],
    )
    session.flush()
    resp = _make(inv, _history(session_factory), range_days=30, service="all")
    # lead seconds: 7200, 14400, 21600 -> median 14400 (4h)
    assert resp.lead_time_median_seconds == 14400
    # p90 (linear interp over sorted [7200,14400,21600], rank=0.9*2=1.8): 14400 + 0.8*7200 = 20160
    assert resp.lead_time_p90_seconds == 20160
    # ci seconds: 3600, 7200, 10800 -> median 7200 (2h)
    assert resp.ci_median_seconds == 7200
    # rollout seconds: 3600, 7200, 10800 -> median 7200 (2h)
    assert resp.rollout_median_seconds == 7200


def test_last_deployed_at_prefers_finished_then_registered(session, session_factory):
    inv = _inventory([_ecs("inventory")])
    repo.upsert_many(
        session,
        [
            # finished_at present and latest go-live
            _event(
                "inventory",
                1,
                datetime(2026, 5, 30, 7, 0, tzinfo=UTC),
                datetime(2026, 5, 30, 6, 0, tzinfo=UTC),
                datetime(2026, 5, 30, 9, 0, tzinfo=UTC),
            ),
            # no finished_at; registered_at is earlier than the above finished_at
            _event("inventory", 2, datetime(2026, 5, 30, 8, 0, tzinfo=UTC)),
        ],
    )
    session.flush()
    resp = _make(inv, _history(session_factory), range_days=30, service="all")
    assert resp.last_deployed_at == datetime(2026, 5, 30, 9, 0, tzinfo=UTC)


def test_last_deployed_at_falls_back_to_registered_when_no_finished(session, session_factory):
    inv = _inventory([_ecs("inventory")])
    repo.upsert_many(
        session,
        [
            _event("inventory", 1, datetime(2026, 5, 30, 7, 0, tzinfo=UTC)),
            _event("inventory", 2, datetime(2026, 5, 30, 11, 0, tzinfo=UTC)),
        ],
    )
    session.flush()
    resp = _make(inv, _history(session_factory), range_days=30, service="all")
    assert resp.last_deployed_at == datetime(2026, 5, 30, 11, 0, tzinfo=UTC)


def test_lead_time_trend_per_day_medians_with_null_gap(session, session_factory):
    # Two deploys finishing on 2026-05-30 (leads 1h + 3h -> median 2h), one on 2026-05-28
    # (lead 1h), and 2026-05-29 has none -> median_seconds None. Trend keyed by finished_at date.
    inv = _inventory([_ecs("inventory")])
    repo.upsert_many(
        session,
        [
            _event(
                "inventory",
                1,
                datetime(2026, 5, 30, 10, 0, tzinfo=UTC),
                datetime(2026, 5, 30, 9, 0, tzinfo=UTC),
                datetime(2026, 5, 30, 10, 0, tzinfo=UTC),  # lead 1h
            ),
            _event(
                "inventory",
                2,
                datetime(2026, 5, 30, 12, 0, tzinfo=UTC),
                datetime(2026, 5, 30, 9, 0, tzinfo=UTC),
                datetime(2026, 5, 30, 12, 0, tzinfo=UTC),  # lead 3h
            ),
            _event(
                "inventory",
                3,
                datetime(2026, 5, 28, 10, 0, tzinfo=UTC),
                datetime(2026, 5, 28, 9, 0, tzinfo=UTC),
                datetime(2026, 5, 28, 10, 0, tzinfo=UTC),  # lead 1h
            ),
        ],
    )
    session.flush()
    resp = _make(inv, _history(session_factory), range_days=30, service="all")
    # spans cutoff.date()..now.date() inclusive, same as count trend
    assert len(resp.lead_time_trend) == 31
    by_day = {b.date: b.median_seconds for b in resp.lead_time_trend}
    assert by_day["2026-05-30"] == 7200  # median(3600, 10800)
    assert by_day["2026-05-28"] == 3600
    assert by_day["2026-05-29"] is None  # null gap day


def test_lead_time_trend_splits_into_ci_and_rollout_per_day(session, session_factory):
    # One deploy on 2026-05-30: committed 9:00, registered 9:20 (CI 20m), finished 9:50
    # (rollout 30m, lead 50m). The per-day bucket carries the stacked components.
    inv = _inventory([_ecs("inventory")])
    repo.upsert_many(
        session,
        [
            _event(
                "inventory",
                1,
                datetime(2026, 5, 30, 9, 20, tzinfo=UTC),  # registered
                datetime(2026, 5, 30, 9, 0, tzinfo=UTC),  # committed
                datetime(2026, 5, 30, 9, 50, tzinfo=UTC),  # finished
            ),
        ],
    )
    session.flush()
    resp = _make(inv, _history(session_factory), range_days=30, service="all")
    bucket = next(b for b in resp.lead_time_trend if b.date == "2026-05-30")
    assert bucket.ci_median_seconds == 1200  # 20m committed→registered
    assert bucket.rollout_median_seconds == 1800  # 30m registered→live
    assert bucket.median_seconds == 3000  # 50m total lead


def test_single_service_filter(session, session_factory):
    inv = _inventory([_ecs("inventory"), _ecs("workforce")])
    repo.upsert_many(
        session,
        [
            _event("inventory", 1, datetime(2026, 5, 30, 10, 0, tzinfo=UTC)),
            _event("workforce", 1, datetime(2026, 5, 30, 11, 0, tzinfo=UTC)),
        ],
    )
    session.flush()
    resp = _make(inv, _history(session_factory), range_days=30, service="inventory")
    assert resp.service == "inventory"
    assert resp.deploy_count == 1  # only inventory's deploy, workforce not queried
    assert resp.services == ["inventory", "workforce"]


def test_unknown_service_zeroed_but_full_services_list(session, session_factory):
    inv = _inventory([_ecs("inventory"), _ecs("workforce")])
    repo.upsert_many(session, [_event("inventory", 1, datetime(2026, 5, 30, 10, 0, tzinfo=UTC))])
    session.flush()
    resp = _make(inv, _history(session_factory), range_days=30, service="ghost")
    assert resp.deploy_count == 0
    assert resp.deploys_per_day == 0.0
    assert resp.lead_time_median_seconds is None
    assert resp.services == ["inventory", "workforce"]
    assert len(resp.trend) == 31
    assert all(b.count == 0 for b in resp.trend)


def test_amplify_only_service_filter_treated_as_unknown(session, session_factory):
    inv = _inventory([_ecs("inventory"), _amplify("web-app")])
    repo.upsert_many(session, [_event("inventory", 1, datetime(2026, 5, 30, 10, 0, tzinfo=UTC))])
    session.flush()
    resp = _make(inv, _history(session_factory), range_days=30, service="web-app")
    assert resp.deploy_count == 0
    assert resp.services == ["inventory"]


def test_swr_cache_keyed_by_range_and_service(session, session_factory):
    inv = _inventory([_ecs("inventory")])
    repo.upsert_many(session, [_event("inventory", 1, datetime(2026, 5, 30, 10, 0, tzinfo=UTC))])
    session.flush()
    svc = MetricsService(
        inventory=inv,
        history=_history(session_factory),
        fresh_seconds=60,
        stale_seconds=300,
        now=lambda: NOW,
    )
    svc.get_metrics(30, "all")
    svc.get_metrics(30, "all")  # cached
    assert inv.get_inventory.call_count == 1
    svc.get_metrics(7, "all")  # different key -> recompute
    assert inv.get_inventory.call_count == 2


def test_busy_service_counts_all_in_window_deploys_beyond_thirty(session, session_factory):
    # Core regression: a busy service with 100 deploys spread across the 30-day window must
    # surface all 100 (not collapse to the newest ~30) with non-zero counts on older days.
    inv = _inventory([_ecs("inventory")])
    events = []
    for i in range(100):
        day_offset = i % 30
        registered = NOW - timedelta(days=day_offset, hours=1)
        events.append(_event("inventory", i, registered))
    repo.upsert_many(session, events)
    session.flush()
    resp = _make(inv, _history(session_factory), range_days=30, service="all")

    assert resp.deploy_count == 100
    counts = {b.date: b.count for b in resp.trend}
    older_day = (NOW - timedelta(days=25)).date().isoformat()
    assert counts[older_day] > 0  # older buckets are populated, not zeroed


def test_default_now_uses_utc_clock(session, session_factory):
    # MetricsService constructed without injecting now: must not raise; produces a sane response.
    inv = _inventory([_ecs("inventory")])
    svc = MetricsService(
        inventory=inv, history=_history(session_factory), fresh_seconds=0, stale_seconds=0
    )
    resp = svc.get_metrics(7, "all")
    assert resp.deploy_count == 0
    assert len(resp.trend) == 8


def test_change_fail_rate_counts_failed_and_rollback(session, session_factory):
    # 4 deploys: 1 failed, 1 rollback, 2 success -> change-fail rate = 2/4 = 0.5.
    inv = _inventory([_ecs("inventory")])
    repo.upsert_many(
        session,
        [
            _event("inventory", 1, datetime(2026, 5, 30, 10, 0, tzinfo=UTC), status="success"),
            _event("inventory", 2, datetime(2026, 5, 30, 11, 0, tzinfo=UTC), status="failed"),
            _event(
                "inventory",
                3,
                datetime(2026, 5, 30, 12, 0, tzinfo=UTC),
                status="success",
                is_rollback=True,
            ),
            _event("inventory", 4, datetime(2026, 5, 30, 13, 0, tzinfo=UTC), status="success"),
        ],
    )
    session.flush()
    resp = _make(inv, _history(session_factory), range_days=30, service="all")
    assert resp.deploy_count == 4
    assert resp.failed_count == 1
    assert resp.rollback_count == 1
    assert resp.change_fail_rate == 0.5
    # fail_trend: 2 failures on 2026-05-30 (failed + rollback), 0 elsewhere.
    fails = {b.date: b.count for b in resp.fail_trend}
    assert fails["2026-05-30"] == 2
    assert fails["2026-05-29"] == 0


def test_change_fail_rate_zero_when_no_deploys(session, session_factory):
    inv = _inventory([_ecs("inventory")])
    resp = _make(inv, _history(session_factory), range_days=30, service="all")
    assert resp.deploy_count == 0
    assert resp.change_fail_rate == 0.0
    assert resp.mttr_median_seconds is None


def test_change_fail_rate_counts_failed_rollback_once(session, session_factory):
    # 2 deploys: 1 failed rollback (status="failed" AND is_rollback=True), 1 success ->
    # change-fail rate = 1/2 = 0.5 (the double-counting bug would report 2/2 = 1.0).
    inv = _inventory([_ecs("inventory")])
    repo.upsert_many(
        session,
        [
            _event(
                "inventory",
                1,
                datetime(2026, 5, 30, 10, 0, tzinfo=UTC),
                status="failed",
                is_rollback=True,
            ),
            _event("inventory", 2, datetime(2026, 5, 30, 11, 0, tzinfo=UTC), status="success"),
        ],
    )
    session.flush()
    resp = _make(inv, _history(session_factory), range_days=30, service="all")
    assert resp.deploy_count == 2
    assert resp.failed_count == 1
    assert resp.rollback_count == 1
    assert resp.change_fail_rate == 0.5


def test_change_fail_rate_never_exceeds_one(session, session_factory):
    # All deploys are failed rollbacks -> change-fail rate must cap at 1.0, not double-count to 2.0.
    inv = _inventory([_ecs("inventory")])
    repo.upsert_many(
        session,
        [
            _event(
                "inventory",
                1,
                datetime(2026, 5, 30, 10, 0, tzinfo=UTC),
                status="failed",
                is_rollback=True,
            ),
            _event(
                "inventory",
                2,
                datetime(2026, 5, 30, 11, 0, tzinfo=UTC),
                status="failed",
                is_rollback=True,
            ),
        ],
    )
    session.flush()
    resp = _make(inv, _history(session_factory), range_days=30, service="all")
    assert resp.deploy_count == 2
    assert resp.change_fail_rate == 1.0


def test_mttr_pairs_failure_with_next_same_service_success(session, session_factory):
    # inventory: failed @10:00 -> success @11:00 (recovery 1h); workforce: failed @10:00 ->
    # success @13:00 (recovery 3h). MTTR = median(3600, 10800) = 7200.
    inv = _inventory([_ecs("inventory"), _ecs("workforce")])
    repo.upsert_many(
        session,
        [
            _event(
                "inventory",
                1,
                datetime(2026, 5, 30, 10, 0, tzinfo=UTC),
                finished_at=datetime(2026, 5, 30, 10, 0, tzinfo=UTC),
                status="failed",
            ),
            _event(
                "inventory",
                2,
                datetime(2026, 5, 30, 11, 0, tzinfo=UTC),
                finished_at=datetime(2026, 5, 30, 11, 0, tzinfo=UTC),
                status="success",
            ),
            _event(
                "workforce",
                1,
                datetime(2026, 5, 30, 10, 0, tzinfo=UTC),
                finished_at=datetime(2026, 5, 30, 10, 0, tzinfo=UTC),
                status="failed",
            ),
            _event(
                "workforce",
                2,
                datetime(2026, 5, 30, 13, 0, tzinfo=UTC),
                finished_at=datetime(2026, 5, 30, 13, 0, tzinfo=UTC),
                status="success",
            ),
        ],
    )
    session.flush()
    resp = _make(inv, _history(session_factory), range_days=30, service="all")
    assert resp.mttr_median_seconds == 7200


def test_mttr_excludes_unrecovered_failure(session, session_factory):
    # A failure with no later success is excluded; only the recovered one (1h) counts.
    inv = _inventory([_ecs("inventory")])
    repo.upsert_many(
        session,
        [
            _event(
                "inventory",
                1,
                datetime(2026, 5, 30, 10, 0, tzinfo=UTC),
                finished_at=datetime(2026, 5, 30, 10, 0, tzinfo=UTC),
                status="failed",
            ),
            _event(
                "inventory",
                2,
                datetime(2026, 5, 30, 11, 0, tzinfo=UTC),
                finished_at=datetime(2026, 5, 30, 11, 0, tzinfo=UTC),
                status="success",
            ),
            # Later failure, never followed by a success -> unrecovered, excluded from MTTR.
            _event(
                "inventory",
                3,
                datetime(2026, 5, 30, 12, 0, tzinfo=UTC),
                finished_at=datetime(2026, 5, 30, 12, 0, tzinfo=UTC),
                status="failed",
            ),
        ],
    )
    session.flush()
    resp = _make(inv, _history(session_factory), range_days=30, service="all")
    assert resp.mttr_median_seconds == 3600  # only the recovered 1h incident


def test_mttr_none_when_no_recovered_incidents(session, session_factory):
    inv = _inventory([_ecs("inventory")])
    repo.upsert_many(
        session,
        [
            _event(
                "inventory",
                1,
                datetime(2026, 5, 30, 10, 0, tzinfo=UTC),
                finished_at=datetime(2026, 5, 30, 10, 0, tzinfo=UTC),
                status="failed",
            ),
        ],
    )
    session.flush()
    resp = _make(inv, _history(session_factory), range_days=30, service="all")
    assert resp.mttr_median_seconds is None


def test_slowest_and_fastest_ordering_and_cap(session, session_factory):
    # 6 deploys with distinct lead times 1h..6h; leaderboards cap at 5 and order correctly.
    inv = _inventory([_ecs("inventory")])
    events = []
    for hours in range(1, 7):
        events.append(
            _event(
                "inventory",
                hours,
                datetime(2026, 5, 20 + hours, 12, 0, tzinfo=UTC),
                committed_at=datetime(2026, 5, 20 + hours, 0, 0, tzinfo=UTC),
                finished_at=datetime(2026, 5, 20 + hours, hours, 0, tzinfo=UTC),
                author=f"a{hours}",
            )
        )
    repo.upsert_many(session, events)
    session.flush()
    resp = _make(inv, _history(session_factory), range_days=30, service="all")

    # Top-5 longest, descending: 6h, 5h, 4h, 3h, 2h (1h dropped by the cap).
    assert len(resp.slowest_deploys) == 5
    assert [e.lead_seconds for e in resp.slowest_deploys] == [
        6 * 3600,
        5 * 3600,
        4 * 3600,
        3 * 3600,
        2 * 3600,
    ]
    # Top-5 shortest, ascending: 1h, 2h, 3h, 4h, 5h (6h dropped by the cap).
    assert len(resp.fastest_deploys) == 5
    assert [e.lead_seconds for e in resp.fastest_deploys] == [
        1 * 3600,
        2 * 3600,
        3 * 3600,
        4 * 3600,
        5 * 3600,
    ]
    # Entries carry service / sha / author / go-live.
    slowest = resp.slowest_deploys[0]
    assert slowest.service == "inventory"
    assert slowest.sha == "inventory-6"
    assert slowest.author == "a6"
    assert slowest.deployed_at == datetime(2026, 5, 26, 6, 0, tzinfo=UTC)


def test_slowest_fastest_skip_deploys_without_valid_lead(session, session_factory):
    inv = _inventory([_ecs("inventory")])
    repo.upsert_many(
        session,
        [
            _event(
                "inventory",
                1,
                datetime(2026, 5, 30, 10, 0, tzinfo=UTC),
                committed_at=datetime(2026, 5, 30, 9, 0, tzinfo=UTC),
                finished_at=datetime(2026, 5, 30, 10, 0, tzinfo=UTC),  # valid 1h
            ),
            _event("inventory", 2, datetime(2026, 5, 30, 11, 0, tzinfo=UTC)),  # no stamps
        ],
    )
    session.flush()
    resp = _make(inv, _history(session_factory), range_days=30, service="all")
    assert len(resp.slowest_deploys) == 1
    assert len(resp.fastest_deploys) == 1
    assert resp.slowest_deploys[0].lead_seconds == 3600


def test_period_over_period_previous_window(session, session_factory):
    # range_days=7 -> current window [now-7d, now), previous [now-14d, now-7d). NOW = 2026-05-31.
    # Current: 2 deploys (1 failed). Previous: 1 deploy (success). Deltas reflect both windows.
    inv = _inventory([_ecs("inventory")])
    repo.upsert_many(
        session,
        [
            # current window
            _event(
                "inventory",
                1,
                datetime(2026, 5, 30, 10, 0, tzinfo=UTC),
                committed_at=datetime(2026, 5, 30, 9, 0, tzinfo=UTC),
                finished_at=datetime(2026, 5, 30, 10, 0, tzinfo=UTC),
                status="success",
            ),
            _event(
                "inventory",
                2,
                datetime(2026, 5, 29, 10, 0, tzinfo=UTC),
                finished_at=datetime(2026, 5, 29, 10, 0, tzinfo=UTC),
                status="failed",
            ),
            # previous window (8-14 days before now)
            _event(
                "inventory",
                3,
                datetime(2026, 5, 20, 10, 0, tzinfo=UTC),
                committed_at=datetime(2026, 5, 20, 8, 0, tzinfo=UTC),  # 2h lead
                finished_at=datetime(2026, 5, 20, 10, 0, tzinfo=UTC),
                status="success",
            ),
        ],
    )
    session.flush()
    resp = _make(inv, _history(session_factory), range_days=7, service="all")

    # Current window: 2 deploys, 1 failure.
    assert resp.deploy_count == 2
    assert resp.change_fail_rate == 0.5
    assert resp.previous is not None
    # Previous window: 1 deploy, no failure, 2h lead.
    assert resp.previous.deploys_per_day == round(1 / 7, 2)
    assert resp.previous.change_fail_rate == 0.0
    assert resp.previous.lead_time_median_seconds == 7200
    assert resp.previous.mttr_median_seconds is None

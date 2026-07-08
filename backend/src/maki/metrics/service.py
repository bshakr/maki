from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from statistics import median

from maki.cache import SwrCache
from maki.history.service import HistoryService
from maki.inventory.service import InventoryService
from maki.schemas import (
    DeployLeadEntry,
    DeployRecord,
    LeadTimeBucket,
    MetricBucket,
    MetricsDelta,
    MetricsResponse,
)


def _percentile(sorted_values: list[float], q: float) -> float:
    """Linear-interpolation percentile (same method as numpy's default 'linear').

    `sorted_values` must be sorted ascending and non-empty. `q` in [0, 1].
    rank = q * (n - 1); interpolate between the two surrounding samples.
    """
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = q * (len(sorted_values) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = rank - lo
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac


def _lead_seconds(record: DeployRecord) -> float | None:
    """Lead time committed→live (finished_at − committed_at), in seconds.

    None when either timestamp is missing or finished_at precedes committed_at. The single
    source of the lead-time rule — both the aggregate and the per-day trend consume it, so the
    exclusion stays in sync.
    """
    if record.committed_at is None or record.finished_at is None:
        return None
    if record.finished_at < record.committed_at:
        return None
    return (record.finished_at - record.committed_at).total_seconds()


def _ci_seconds(record: DeployRecord) -> float | None:
    """CI/build time committed→registered, in seconds. None if a stamp is missing or negative."""
    if record.committed_at is None or record.registered_at is None:
        return None
    if record.registered_at < record.committed_at:
        return None
    return (record.registered_at - record.committed_at).total_seconds()


def _rollout_seconds(record: DeployRecord) -> float | None:
    """Rollout time registered→live, in seconds. None if a stamp is missing or negative."""
    if record.registered_at is None or record.finished_at is None:
        return None
    if record.finished_at < record.registered_at:
        return None
    return (record.finished_at - record.registered_at).total_seconds()


def _is_failure(record: DeployRecord) -> bool:
    """A change failure for change-fail-rate: a failed rollout OR a rollback."""
    return record.status == "failed" or record.is_rollback


def _go_live(record: DeployRecord) -> datetime | None:
    """Go-live moment used by MTTR pairing: finished_at, falling back to registered_at."""
    return record.finished_at or record.registered_at


def _change_fail_rate(deploy_count: int, failure_count: int) -> float:
    """failures (failed rollout OR rollback, counted once) / deploy_count; 0.0 when no deploys."""
    if deploy_count == 0:
        return 0.0
    return failure_count / deploy_count


def _mttr_recoveries(kept: list[tuple[str, DeployRecord]]) -> list[float]:
    """Recovery durations (seconds) per service: each failure → its NEXT same-service success.

    Walks each service's events in go-live order. For every failed/rollback deploy, scans forward to
    the first later ``status == "success"`` deploy of that same service and records
    (success go-live − failure go-live). Unrecovered failures (no later success) are skipped, as are
    events missing a go-live stamp. Best-effort: a service with no recovered incident contributes
    nothing.
    """
    by_service: dict[str, list[DeployRecord]] = {}
    for name, record in kept:
        if _go_live(record) is not None:
            by_service.setdefault(name, []).append(record)

    recoveries: list[float] = []
    for records in by_service.values():
        ordered = sorted(records, key=lambda r: _go_live(r))  # type: ignore[arg-type, return-value]
        for i, record in enumerate(ordered):
            if not _is_failure(record):
                continue
            failed_at = _go_live(record)
            for later in ordered[i + 1 :]:
                if later.status == "success" and not _is_failure(later):
                    recovered_at = _go_live(later)
                    if recovered_at is not None and failed_at is not None:
                        recoveries.append((recovered_at - failed_at).total_seconds())
                    break
    return recoveries


def _lead_leaderboard(
    kept: list[tuple[str, DeployRecord]],
) -> tuple[list[DeployLeadEntry], list[DeployLeadEntry]]:
    """(slowest_top5, fastest_top5) by lead time over deploys with a valid committed→live lead."""
    entries = [
        DeployLeadEntry(
            service=name,
            sha=record.sha,
            author=record.author,
            lead_seconds=int(lead),
            deployed_at=record.finished_at,
        )
        for name, record in kept
        if (lead := _lead_seconds(record)) is not None
    ]
    ranked = sorted(entries, key=lambda e: e.lead_seconds)
    fastest = ranked[:5]
    slowest = list(reversed(ranked[-5:]))
    return slowest, fastest


class MetricsService:
    """DORA-style delivery metrics over the deploy-events store.

    ECS services only — Amplify has no revision timeline. Reads enriched deploy records from the
    store-backed HistoryService (no live ECS fan-out); the ingester is the only AWS caller.
    """

    def __init__(
        self,
        inventory: InventoryService,
        history: HistoryService,
        fresh_seconds: float,
        stale_seconds: float,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._inventory = inventory
        self._history = history
        self._now = now
        self._cache = SwrCache(fresh_seconds, stale_seconds)

    def get_metrics(self, range_days: int, service: str, force: bool = False) -> MetricsResponse:
        return self._cache.get(
            (range_days, service),
            lambda: self._compute(range_days, service),
            force=force,
        )

    def _headline(
        self, kept: list[tuple[str, DeployRecord]], range_days: int
    ) -> MetricsDelta:
        """The four DORA headline metrics over an arbitrary window's kept (name, record) pairs.

        Shared by the current window and the previous equal-length window so both are computed the
        exact same way. Lead median nullability matches the headline field.
        """
        deploy_count = len(kept)
        lead_times = [s for _, record in kept if (s := _lead_seconds(record)) is not None]
        failure_count = sum(1 for _, record in kept if _is_failure(record))
        recoveries = _mttr_recoveries(kept)
        return MetricsDelta(
            deploys_per_day=round(deploy_count / range_days, 2),
            lead_time_median_seconds=int(median(lead_times)) if lead_times else None,
            change_fail_rate=_change_fail_rate(deploy_count, failure_count),
            mttr_median_seconds=int(median(recoveries)) if recoveries else None,
        )

    def _kept_in_window(
        self, targets: list[str], cutoff: datetime, until: datetime | None
    ) -> list[tuple[str, DeployRecord]]:
        """(name, record) pairs registered in [cutoff, until). ``until`` None means open-ended."""
        kept: list[tuple[str, DeployRecord]] = []
        for name in targets:
            for record in self._history.get_deployments_since(name, cutoff):
                registered = record.registered_at
                if registered is None or registered < cutoff:
                    continue
                if until is not None and registered >= until:
                    continue
                kept.append((name, record))
        return kept

    def _compute(self, range_days: int, service: str) -> MetricsResponse:
        now = self._now()
        cutoff = now - timedelta(days=range_days)
        prev_cutoff = now - timedelta(days=2 * range_days)

        ecs_names = sorted(
            svc.name for svc in self._inventory.get_inventory().services if svc.platform == "ecs"
        )

        if service == "all":
            targets = ecs_names
        elif service in ecs_names:
            targets = [service]
        else:
            targets = []

        kept = self._kept_in_window(targets, cutoff, until=None)
        # Previous equal-length window [2×range, range) for period-over-period deltas.
        prev_kept = self._kept_in_window(targets, prev_cutoff, until=cutoff)
        previous = self._headline(prev_kept, range_days)

        deploy_count = len(kept)
        deploys_per_day = round(deploy_count / range_days, 2)

        # Change-fail: failed rollouts + rollbacks over the window; a failed rollback counts once.
        failed_count = sum(1 for _, record in kept if record.status == "failed")
        rollback_count = sum(1 for _, record in kept if record.is_rollback)
        failure_count = sum(1 for _, record in kept if _is_failure(record))
        change_fail_rate = _change_fail_rate(deploy_count, failure_count)

        # MTTR: median recovery (failure go-live → next same-service success go-live) within window.
        recoveries = _mttr_recoveries(kept)
        mttr_median_seconds = int(median(recoveries)) if recoveries else None

        # Slowest / fastest leaderboards (top-5 each) over deploys with a valid lead time.
        slowest_deploys, fastest_deploys = _lead_leaderboard(kept)

        # Lead time = committed_at → finished_at (merge to fully-in-prod go-live), via the shared
        # _lead_seconds rule (excludes records missing either stamp or with finished < committed).
        lead_times = [s for _, record in kept if (s := _lead_seconds(record)) is not None]
        ci_times = [s for _, record in kept if (s := _ci_seconds(record)) is not None]
        rollout_times = [s for _, record in kept if (s := _rollout_seconds(record)) is not None]

        lead_time_median_seconds = int(median(lead_times)) if lead_times else None
        lead_time_p90_seconds = int(_percentile(sorted(lead_times), 0.9)) if lead_times else None
        ci_median_seconds = int(median(ci_times)) if ci_times else None
        rollout_median_seconds = int(median(rollout_times)) if rollout_times else None

        # Most recent go-live across the window: prefer finished_at, fall back to registered_at.
        live_stamps = [
            record.finished_at or record.registered_at
            for _, record in kept
            if record.finished_at is not None or record.registered_at is not None
        ]
        last_deployed_at = max(live_stamps) if live_stamps else None

        # Two trends keyed by DIFFERENT dates on purpose: the count trend by registered_at (when a
        # revision landed on ECS — "how many deploys that day") and the lead-time trend by
        # finished_at (when it went live — "how long did things that went live that day take").
        # They measure different events; don't "align" the keys.
        counts_by_day: dict[str, int] = {}
        # Fail markers: failed rollouts + rollbacks, keyed by registered_at date (same axis as the
        # count trend so the overlay aligns bar-for-bar).
        fails_by_day: dict[str, int] = {}
        for _, record in kept:
            day = record.registered_at.date().isoformat()
            counts_by_day[day] = counts_by_day.get(day, 0) + 1
            if _is_failure(record):
                fails_by_day[day] = fails_by_day.get(day, 0) + 1

        # Per-day component buckets, all keyed by finished_at date so the stacked CI + rollout
        # trend aligns with the day each deploy went live.
        lead_by_day: dict[str, list[float]] = {}
        ci_by_day: dict[str, list[float]] = {}
        rollout_by_day: dict[str, list[float]] = {}
        for _, record in kept:
            if record.finished_at is None:
                continue
            day = record.finished_at.date().isoformat()
            for value, bucket in (
                (_lead_seconds(record), lead_by_day),
                (_ci_seconds(record), ci_by_day),
                (_rollout_seconds(record), rollout_by_day),
            ):
                if value is not None:
                    bucket.setdefault(day, []).append(value)

        def _day_median(bucket: dict[str, list[float]], key: str) -> int | None:
            values = bucket.get(key)
            return int(median(values)) if values else None

        trend: list[MetricBucket] = []
        fail_trend: list[MetricBucket] = []
        lead_time_trend: list[LeadTimeBucket] = []
        day = cutoff.date()
        end = now.date()
        while day <= end:
            key = day.isoformat()
            trend.append(MetricBucket(date=key, count=counts_by_day.get(key, 0)))
            fail_trend.append(MetricBucket(date=key, count=fails_by_day.get(key, 0)))
            lead_time_trend.append(
                LeadTimeBucket(
                    date=key,
                    median_seconds=_day_median(lead_by_day, key),
                    ci_median_seconds=_day_median(ci_by_day, key),
                    rollout_median_seconds=_day_median(rollout_by_day, key),
                )
            )
            day += timedelta(days=1)

        return MetricsResponse(
            range_days=range_days,
            service=service,
            deploy_count=deploy_count,
            deploys_per_day=deploys_per_day,
            lead_time_median_seconds=lead_time_median_seconds,
            lead_time_p90_seconds=lead_time_p90_seconds,
            ci_median_seconds=ci_median_seconds,
            rollout_median_seconds=rollout_median_seconds,
            last_deployed_at=last_deployed_at,
            failed_count=failed_count,
            rollback_count=rollback_count,
            change_fail_rate=change_fail_rate,
            fail_trend=fail_trend,
            mttr_median_seconds=mttr_median_seconds,
            previous=previous,
            slowest_deploys=slowest_deploys,
            fastest_deploys=fastest_deploys,
            trend=trend,
            lead_time_trend=lead_time_trend,
            services=ecs_names,
            generated_at=now,
        )

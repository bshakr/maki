# P5 — Metrics Page Implementation Plan

**Goal:** Build the `/metrics` page: DORA-style delivery metrics derived honestly from ECS
task-definition revisions (the deploy timeline) + GitHub commit timestamps. No persistent
ledger exists, so only truthfully-computable metrics ship.

**Architecture:** Backend `MetricsService` aggregates per-ECS-service deploy history (reusing the
existing `HistoryService` pipeline, which is already SWR-cached + GitHub-enriched), buckets deploys
by day, and computes summary stats. New `GET /api/metrics` endpoint. Frontend `MetricsPage` renders
3 stat cards + a deploys/day bar chart (shadcn chart / recharts) with range + service filters via
TanStack Query.

**Tech Stack:** FastAPI + pydantic v2 (backend), React + TanStack Query + shadcn chart (recharts).

**Scope — real-only metric set (user decision 2026-05-31):**
- ✅ Deploy frequency (deploys/day over range)
- ✅ Total deploys (range)
- ✅ Median lead time (commit committed_at → deploy registered_at)
- ✅ Deploys-over-time trend (per-day buckets)
- ❌ Rollbacks / change-fail rate / MTTR — **omitted**, need a ledger / incident source. Do NOT
  fabricate or heuristically infer them.
- ECS services only. Amplify (web-app) has no revision timeline → excluded from metrics.

---

## Pinned API contract (both backend + frontend agents implement THIS exactly)

`GET /api/metrics?range_days=30&service=all&refresh=0`

- `range_days`: int, one of {7, 30, 90}, default 30.
- `service`: ECS service name, or `"all"` (default) for fleet-wide.
- `refresh`: bool, bypasses SWR cache (`?refresh=1`), same convention as other endpoints.

Response (`MetricsResponse`):

```json
{
  "range_days": 30,
  "service": "all",
  "deploy_count": 247,
  "deploys_per_day": 8.23,
  "lead_time_median_seconds": 11520,
  "trend": [
    { "date": "2026-05-02", "count": 6 },
    { "date": "2026-05-03", "count": 9 }
  ],
  "services": ["forecasting", "inventory", "newsfeed", "workforce"],
  "generated_at": "2026-05-31T10:00:00Z"
}
```

Field rules:
- `deploys_per_day` = `deploy_count / range_days`, rounded to 2 dp.
- `lead_time_median_seconds`: median over deploys where BOTH `committed_at` and `registered_at`
  are present and `registered_at >= committed_at`. `null` if no such deploys.
- `trend`: one entry per calendar day (UTC) across the full range, **including zero-count days**,
  oldest→newest. `date` is `YYYY-MM-DD`.
- `services`: sorted list of all ECS service names available as filter options (always the full
  fleet, independent of the `service` filter applied).

---

## Task M0 (backend): add commit timestamp to enrichment

Lead time needs the commit's authored/committed time. The GitHub enricher already fetches the
commit; surface its timestamp.

**Files:**
- Modify: `backend/src/maki/schemas.py` (`CommitInfo`, `DeployRecord`)
- Modify: `backend/src/maki/github_enrich.py` (`GitHubEnricher.commit`)
- Modify: `backend/src/maki/history/service.py` (`HistoryService._compute`)
- Test: `backend/tests/test_github_enrich.py`, `backend/tests/test_history_service.py`

Steps:
- [ ] Add `committed_at: datetime | None = None` to `CommitInfo`.
- [ ] Add `committed_at: datetime | None = None` to `DeployRecord` (after `pr_url`).
- [ ] In `GitHubEnricher.commit`, parse the commit timestamp from the GitHub response. The commits
      API returns `commit.committer.date` (ISO-8601, e.g. `"2026-05-30T09:15:00Z"`). Parse to a
      timezone-aware `datetime` and set `committed_at` on the returned `CommitInfo`. Be defensive:
      if the field is missing/unparseable, leave it `None` (do not raise).
- [ ] In `HistoryService._compute`, after the existing enrich block, set
      `record.committed_at = info.committed_at`.
- [ ] Test: enricher parses `commit.committer.date` into `committed_at`; missing field → `None`.
- [ ] Test: history service copies `committed_at` onto the record.
- [ ] Run `python -m pytest -q` from `backend/` (venv active). All pass.

## Task M1 (backend): MetricsService + route + schemas  — depends on M0

**Files:**
- Modify: `backend/src/maki/schemas.py` (`MetricBucket`, `MetricsResponse`)
- Create: `backend/src/maki/metrics/__init__.py`
- Create: `backend/src/maki/metrics/service.py`
- Create: `backend/src/maki/metrics/routes.py`
- Modify: `backend/src/maki/api.py` (include metrics router)
- Test: `backend/tests/test_metrics_service.py`, `backend/tests/test_metrics_route.py`

Schemas:
```python
class MetricBucket(BaseModel):
    date: str   # YYYY-MM-DD (UTC)
    count: int

class MetricsResponse(BaseModel):
    range_days: int
    service: str
    deploy_count: int
    deploys_per_day: float
    lead_time_median_seconds: int | None = None
    trend: list[MetricBucket]
    services: list[str]
    generated_at: datetime
```

`MetricsService` design:
- Constructor deps: `inventory: InventoryService` (to enumerate ECS service names + filter options),
  `history: HistoryService` (reuse its cached, enriched per-service deploy pipeline),
  `fresh_seconds`, `stale_seconds`, `now: Callable[[], datetime] = lambda: datetime.now(UTC)`
  (inject the clock so tests are deterministic — do NOT call `datetime.now` inline).
- `get_metrics(range_days: int, service: str, force: bool = False) -> MetricsResponse`, SWR-cached
  with key `(range_days, service)`.
- `_compute(range_days, service)`:
  - `now = self._now()`; `cutoff = now - timedelta(days=range_days)`.
  - ECS service names: from `inventory.get_inventory().services` where `platform == "ecs"`,
    sorted. This is the `services` filter list.
  - Target set: if `service == "all"` → all ECS names; else `[service]` (only if it's a known ECS
    service, otherwise empty target set → zeroed response).
  - For each target service: `history.get_deployments(name).deployments`; keep records with
    `registered_at is not None and registered_at >= cutoff`.
  - `deploy_count` = total kept records across targets.
  - `deploys_per_day` = `round(deploy_count / range_days, 2)`.
  - Lead times: for kept records with `committed_at` and `registered_at` and
    `registered_at >= committed_at`, collect `(registered_at - committed_at).total_seconds()`.
    `lead_time_median_seconds` = `int(median(...))` or `None` if empty.
  - `trend`: build a dict of `date_str -> count` from kept records' `registered_at.date()`, then
    emit one `MetricBucket` per day from `cutoff.date()` to `now.date()` inclusive (zero-fill gaps),
    oldest→newest.
- Use `statistics.median`. Import all deps at module top.

Route (`metrics/routes.py`), mirror `activity/routes.py`:
```python
@cache
def get_metrics_service() -> MetricsService: ...
@router.get("/metrics", response_model=MetricsResponse)
def get_metrics(range_days: int = 30, service: str = "all", refresh: bool = False) -> MetricsResponse:
    return get_metrics_service().get_metrics(range_days, service, force=refresh)
```
Build `MetricsService` from `get_inventory_service()` + a `HistoryService` (construct the same way
`history/routes.py` does — reuse `get_history_service()` if one exists; otherwise build it here with
the same client/enricher/settings wiring). Include `metrics_router` in `api.py` BEFORE `mount_spa`.

Tests (mocked, zero network):
- [ ] `_compute` with a fake inventory (2 ECS + 1 amplify) and a fake history returning deploys at
      known timestamps → asserts deploy_count, deploys_per_day, median lead time, zero-filled trend
      length == range_days+1, services list excludes amplify.
- [ ] `service=<one>` filters to that service only; unknown service → zeroed counts but full
      `services` list still returned.
- [ ] Route returns 200 + shape via FastAPI TestClient with service deps overridden/mocked.
- [ ] Run `python -m pytest -q` from `backend/`. All pass.

## Task M2 (frontend): api client + types  — parallel-safe with M0/M1 (implements pinned contract)

**Files:**
- Modify: `frontend/src/api.ts`

Steps:
- [ ] Add `committed_at: string | null;` to the `DeployRecord` interface (after `pr_url`).
- [ ] Add interfaces matching the pinned contract:
```ts
export interface MetricBucket { date: string; count: number; }
export interface MetricsResponse {
  range_days: number;
  service: string;
  deploy_count: number;
  deploys_per_day: number;
  lead_time_median_seconds: number | null;
  trend: MetricBucket[];
  services: string[];
  generated_at: string;
}
export async function fetchMetrics(opts?: {
  rangeDays?: number; service?: string; refresh?: boolean;
}): Promise<MetricsResponse> {
  const p = new URLSearchParams();
  if (opts?.rangeDays) p.set("range_days", String(opts.rangeDays));
  if (opts?.service) p.set("service", opts.service);
  if (opts?.refresh) p.set("refresh", "1");
  const qs = p.toString();
  const r = await fetch(`/api/metrics${qs ? `?${qs}` : ""}`);
  if (!r.ok) throw new Error(`Failed to load metrics: ${r.status}`);
  return r.json();
}
```

## Task M3 (frontend): install chart + build MetricsPage  — depends on M2

**Files:**
- Run: `npx shadcn@latest add chart` (from `frontend/`, zinc preset — matches existing components;
  installs recharts + `components/ui/chart.tsx`). Verify no base-color drift.
- Rewrite: `frontend/src/pages/MetricsPage.tsx`
- Test: `frontend/src/pages/MetricsPage.test.tsx`

`MetricsPage` requirements (match existing page conventions — see `ActivityPage.tsx`):
- TanStack Query: `queryKey: ["metrics", rangeDays, service]`,
  `queryFn: () => fetchMetrics({ rangeDays, service, refresh })` with the same `forceNext` ref
  pattern for manual Refresh as ActivityPage.
- Controls row: range `Select` (7d / 30d / 90d), service `Select` (`all` + `data.services`),
  Refresh button (spinner + "updating…" like ActivityPage). Keep `data` while refetching.
- 3 stat cards (shadcn `Card`): **Deploy freq** (`deploys_per_day` + "/day"),
  **Total deploys** (`deploy_count` over range), **Lead time (median)** — format
  `lead_time_median_seconds` via a small helper into `Xh Ym` (or "—" when null).
- Trend chart: shadcn `ChartContainer` + recharts `BarChart` of `trend` (x = date, y = count).
  Use the existing chart-* theme tokens.
- States: loading skeleton, error (role="alert", same style as ActivityPage), empty
  (`deploy_count === 0` → "No deploys in the last Nd").
- Root element keeps `data-testid="metrics-page"`.
- Add a `formatDuration(seconds: number | null): string` helper — co-locate in
  `frontend/src/lib/format.ts` (returns "—" for null, else compact `Xh Ym` / `Ym` / `Xd Yh`).

Tests (vitest + renderWithProviders + mocked `fetchMetrics`):
- [ ] Renders 3 stat cards with formatted values from a mocked response.
- [ ] Lead time "—" when `lead_time_median_seconds` is null.
- [ ] Empty state when `deploy_count === 0`.
- [ ] Changing the range select refetches (mock asserts called with new `rangeDays`).
- [ ] `npx vitest run` green + `npm run build` green.

---

## Execution order

1. **Parallel batch:** M0+M1 (backend agent) ∥ M2 (frontend api agent). Different folders, no file
   conflict; both honor the pinned contract above.
2. M3 (frontend page agent) — after M2 (needs `fetchMetrics`/types) and M1 (live endpoint to
   smoke-test, though tests mock fetch).

Each task: subagent runs plan → implement → `/code-review` → fix all findings → local commit.
Controller verifies HEAD advanced + tests/build green after each.

# Metrics date-window fix — implementation plan

**Goal:** Metrics must reflect ALL deploys within the selected range (7/30/90d), not just the newest
30 task-def revisions per service. Today `HistoryService` caps at 30 revisions/service and
`MetricsService` reuses that, so busy services' history collapses to the last day or two and the
deploys-over-time chart shows near-zero for older days with everything piled in the newest bar.

**Root cause:** `ECSDeployHistory.list_deploys(family, limit=30)` (count cap) →
`HistoryService` default `limit=30` → `MetricsService._compute` iterates
`self._history.get_deployments(name).deployments` (30-capped) and filters by `registered_at >= cutoff`.
A count cap is wrong for variable deploy churn; metrics needs a **date-bounded** fetch.

**Approach:** Add a date-bounded fetch path that walks revisions newest→oldest (the list API is
sorted DESC), describes each, keeps while `registered_at >= since`, and stops early once a revision is
older than `since`. A hard safety cap bounds worst-case fan-out; when hit, `log` a warning (NO silent
truncation). Metrics uses `since = now - range_days`. Service-detail HISTORY card is unchanged
(newest-30 is correct there).

**Tech stack:** FastAPI + boto3 (mocked in tests), pydantic v2.

**Scope:** metrics only. ECS-only (unchanged). No new metrics. No frontend change.

---

## Task 1 (backend): date-bounded deploy fetch for metrics

**Files:**
- Modify: `backend/src/maki/aws/ecs_history.py`
- Modify: `backend/src/maki/history/service.py`
- Modify: `backend/src/maki/metrics/service.py`
- Modify: `backend/src/maki/settings.py` (safety-cap setting)
- Test: `backend/tests/` — ecs_history, history service, metrics service

### `ECSDeployHistory` — bound by date with early stop

Add an optional `since: datetime | None` and a `max_revisions` safety cap to the fetch:

- New/extended method, e.g. `list_deploys(self, family, limit=30, since=None, max_revisions=None)`:
  - When `since is None`: current behaviour (newest `limit`).
  - When `since` is set: paginate `list_task_definitions(familyPrefix, status="ACTIVE", sort="DESC")`,
    convert each ARN to a `DeployRecord` (existing `_to_record`, which describes + caches per ARN),
    **append while `record.registered_at is None or record.registered_at >= since`**, and **break as
    soon as** a record has `registered_at` and `registered_at < since` (DESC order ⇒ everything after
    is older). Guard with `max_revisions`: stop and mark truncated if the kept count reaches it.
  - Return value stays `list[DeployRecord]`. Signal truncation to the caller — simplest: return the
    list and have the method `log`/warn when it hit `max_revisions` (import the module logger). Do
    NOT silently cap.
- Keep `_to_record`'s per-ARN cache + `model_copy()` semantics intact.

### `HistoryService` — expose a date-bounded, enriched fetch

Service-detail keeps using `get_deployments(name)` (newest-30, unchanged). Add a separate path for
metrics that returns enriched records since a cutoff:

- Add `get_deployments_since(self, service_name, since, force=False) -> list[DeployRecord]` (or a
  `since` param threaded through a shared compute). It must run the SAME GitHub enrichment as
  `_compute` (author/message/commit_url/pr_url/**committed_at**) so lead time still works.
- Cache it under a key that includes `since` bucketed sensibly (e.g. the cutoff date, not the exact
  timestamp, so repeated calls in a window share a cache entry) — e.g. SWR key
  `("since", service_name, since.date().isoformat())`. Reuse the existing SWR cache instance.
- Pass `max_revisions` from settings down to `ECSDeployHistory`.

### `MetricsService._compute` — fetch by cutoff

- Replace `self._history.get_deployments(name).deployments` with
  `self._history.get_deployments_since(name, cutoff)`.
- Everything downstream (deploy_count, deploys_per_day, lead time, zero-filled trend, services list)
  is unchanged.

### `settings.py`

- Add `metrics_max_revisions_per_service: int = 1000` (env-overridable). Used as the safety cap.
  Document inline that hitting it means the window is under-counted for very busy services and that
  the precompute/ledger backlog item is the real fix.

### Tests (mocked, ZERO network)

- [ ] `ECSDeployHistory` with `since`: a fake client returning revisions with descending
      `registeredAt` (some inside, some outside the window) → only in-window kept, and `describe` is
      NOT called for revisions beyond the first out-of-window one (assert early stop, e.g. via
      `describe_task_definition` call count).
- [ ] `max_revisions` cap: more in-window revisions than the cap → result length == cap and a warning
      is logged (assert via `caplog`).
- [ ] `since=None` path unchanged (regression).
- [ ] `HistoryService.get_deployments_since` enriches records (author/committed_at set) and caches by
      cutoff-date key (second call within same day doesn't re-describe — assert loader called once).
- [ ] `MetricsService._compute` now counts in-window deploys beyond 30 for a busy fake service (the
      core regression: feed a service with 100 deploys spread across 30 days → trend has non-zero
      counts on older days, deploy_count == 100, not 30).
- [ ] Run `python -m pytest -q` from `backend/` (venv active). All green.

---

## Notes
- This increases AWS `describe_task_definition` calls and GitHub enrich calls for the metrics path.
  Acceptable interim; the **precompute-metrics** backlog item (build the per-service timeline once in
  the background, ideally atop a SQLite ledger) is the real scaling answer. Cross-reference it.
- If Nory deregisters old task defs, ACTIVE history (all maki can read) is bounded by that — surfaces
  as a hard oldest-date floor once the cap is lifted. Expected, not a bug.

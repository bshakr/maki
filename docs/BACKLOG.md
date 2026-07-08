# maki — Backlog (local, future work)

Local-only future-task list. Not tickets. Newest ideas at top. Pull one into a dated plan under
`docs/plans/` when starting it.

---

## Live deploy stages + task status on the current-deploy card

**Why:** the current-deploy section shows a static snapshot. During an active rollout we want to see
it progress — the ECS deployment stages, how many tasks are coming up vs draining, and live updates.

**What:**
- Show the deployment rollout **stages / state** (e.g. registered → in-progress → completed) with the
  per-state task counts ECS exposes on the primary deployment: `desiredCount`, `runningCount`,
  `pendingCount`, plus the `rolloutState`/`rolloutStateReason`. The service's `deployments[]` array
  (from `describe_services`) also lists ACTIVE (old) deployments still draining — show new-up vs
  old-draining.
- **Poll** for updates while a deploy is IN_PROGRESS (short interval, e.g. 3–5s) and stop once
  COMPLETED — a small per-service status endpoint `GET /api/services/{name}/rollout` returning the
  primary + active deployments with their counts + timestamps; the UI polls it (TanStack Query
  `refetchInterval` gated on in-progress).
- Live counts during a rollout (`runningCount`/`pendingCount`/`desiredCount`) come from the primary
  `deployment` on `describe_services`; the literal last-task time is `max(task.startedAt)`
  (`list_tasks`+`describe_tasks`) or the primary deployment `updatedAt` at COMPLETED.

**Notes:** read-only ECS (`describe_services`, `list_tasks`, `describe_tasks`) — no writes. Per-task
calls are per-service and only needed on the detail page (cheap); don't fan this out across the whole
fleet on `/services`.

## Lead time beyond ECS's 90-day window (needs the ledger)

**Context (corrected — earlier note was wrong):** accurate "merged → fully in production" lead time
DOES NOT require the ledger for recent deploys. ECS exposes first-class deployment history via
`ListServiceDeployments` / `DescribeServiceDeployments`, which return per-deployment `startedAt`,
**`finishedAt`** (= fully in production), `status`, and `targetServiceRevisionArn`. Correlate the
target service revision → task-def revision (`DescribeServiceRevisions` → `taskDefinition`) → match
to each history row → lead time = `finishedAt − committed_at`. This is computed at **request time, no
ledger** (implemented for the service-detail history; see that work).

**Status (2026-06-01): the store is built (P2.5) and now persists `finished_at` forward.**
- ECS keeps only the **most recent 90 days** of service-deployment history (deployments created
  on/after 2024-10-25); beyond that window `finishedAt` is gone from AWS.
- The **deploy-events store** persists each deploy's `finished_at` (captured by the ingester while
  it's still inside the 90-day window), so history older than 90 days keeps an accurate go-live time —
  durable going FORWARD, not a backfill of pre-store deploys. The per-request `ListServiceDeployments`
  + revision-correlation cost is gone (the ingester does it once).
- ✅ DONE (2026-07-08): Metrics page lead time now computes `committed_at → finished_at`
  (`backend/src/maki/metrics/service.py::_lead_seconds`) instead of `registered_at`. No per-request
  AWS calls; reads the store like everything else.

## Precompute metrics (background) — ✅ DONE (P2.5, 2026-06-01)

Satisfied by the deploy-events store + background ingester. The ingester builds the per-service deploy
timeline (enriched, with `finished_at`) into Postgres every ~5 min; `/api/metrics`, `/deployments`,
and `/activity` now read the store with a single indexed SQL query instead of fanning out to AWS +
GitHub on the request path. Cold reads are instant and survive restarts. The old
`metrics_max_revisions_per_service` cap (which under-counted busy services) is removed — metrics read
every in-window event. See ARCHITECTURE §9 (Status) and the plans under `docs/plans/`.

Still open (minor): `SwrCache` has no eviction — the date-bucketed `get_deployments_since` keys grow
slowly in a long-running process. Negligible for a local prototype that restarts often; add LRU/TTL to
`SwrCache` if it ever matters. New metrics (rollback count / change-fail) still await action records.

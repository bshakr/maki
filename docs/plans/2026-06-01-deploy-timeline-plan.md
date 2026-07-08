# Full deploy timeline (merge → CI → rollout → live)

**Goal:** for a deploy, show the full path from PR merge to live in production, broken into timed
segments spanning **GitHub Actions** (build/test/deploy jobs) and **ECS** (queued → rollout), so you
can see where the time went — the maki equivalent of Railway's per-stage breakdown, but across both
the CI system and the orchestrator (which Railway doesn't have to span because it owns the builder).

**Scope:** the CURRENT deploy on the service-detail page first. Read-only. Fully failure-isolated:
any missing source degrades to fewer segments, never an error.

---

## Data sources per segment

| Segment | Source | Timestamps |
|---|---|---|
| merge | commit committer date (`committed_at`, already enriched) | start = merge point |
| CI jobs (Build, Test, Deploy, …) | **GitHub Actions** — runs+jobs for the commit sha | each job `started_at`→`completed_at` |
| ECS queued | ECS service deployment | `createdAt`→`startedAt` |
| ECS rollout | ECS service deployment | `startedAt`→`finishedAt` |
| live | ECS service deployment | `finishedAt` |

GitHub Actions: `GET {api}/repos/{repo}/actions/runs?head_sha={sha}` → runs; for each run
`GET .../actions/runs/{id}/jobs` → jobs with `name`, `started_at`, `completed_at`, `conclusion`.
Build one segment per job, ordered by `started_at`. Cache by sha (Actions has rate limits). Token =
`settings.github_token` (same one used for commits; needs `actions:read`).

ECS: extend `ECSServiceDeployments` with `deployment_for_revision(service, revision) ->
{created_at, started_at, finished_at, status} | None` (reuse the list+describe correlation already
built for `finished_at_by_revision`).

---

## Pinned API contract

`GET /api/services/{name}/deploy-timeline` → `DeployTimeline`:

```json
{
  "service": "wfm-service",
  "sha": "cf930b6",
  "merged_at": "2026-05-29T04:00:00Z",
  "live_at": "2026-05-29T07:00:00Z",
  "total_seconds": 10800,
  "segments": [
    { "key": "ci:build",   "label": "Build",   "source": "github_actions",
      "start": "...", "end": "...", "seconds": 38,  "status": "success" },
    { "key": "ci:test",    "label": "Test",    "source": "github_actions",
      "start": "...", "end": "...", "seconds": 72,  "status": "success" },
    { "key": "ecs:queued", "label": "Queued",  "source": "ecs",
      "start": "...", "end": "...", "seconds": 12,  "status": "success" },
    { "key": "ecs:rollout","label": "Rollout", "source": "ecs",
      "start": "...", "end": "...", "seconds": 184, "status": "success" }
  ],
  "generated_at": "..."
}
```

- `segments` ordered by `start`; gaps between segments are allowed (the viz can show idle time).
- `status` ∈ {success, failed, in_progress, unknown} per segment (from Actions conclusion / ECS state).
- `source` ∈ {github_actions, ecs}.
- `total_seconds` = `live_at − merged_at` when both known, else null.
- **Degradation:** no token / no Actions run for sha → CI segments omitted. ECS deployment gone
  (>90d / pre-2024-10-25) → ECS segments omitted. Nothing resolvable → `segments: []` and totals
  from whatever timestamps exist. NEVER raise; log + return partial.

This shape is viz-agnostic — supports a proportional bar, a vertical stepper, or a milestone line.

---

## Backend tasks
- New `backend/src/maki/aws/service_deployments.py` method `deployment_for_revision(...)`.
- New `backend/src/maki/github_actions.py` — `GitHubActions` client: `jobs_for_sha(repo, sha) ->
  list[{name, started_at, completed_at, conclusion}]`, httpx + token, sha-cached, defensive (→ [] on
  any failure).
- New `backend/src/maki/timeline/{__init__,service,routes}.py` — `TimelineService` assembles the
  contract from current service (sha/committed_at/revision) + ECS deployment + Actions jobs; route
  `GET /api/services/{name}/deploy-timeline`. Wire router in `api.py`. SWR-cache by service.
- `schemas.py`: `TimelineSegment`, `DeployTimeline`.
- Tests (mocked, zero network): Actions jobs → CI segments; ECS deployment → queued/rollout; ordering
  by start; each degradation path (no token, no run, no ecs deployment) → partial, no raise.

## Frontend tasks (viz — chosen separately)
- `api.ts`: `TimelineSegment`/`DeployTimeline` types + `fetchDeployTimeline(name)`.
- A `DeployTimeline` component rendering the chosen visualization (see exploration), placed in/under
  the current-deploy section. TanStack Query keyed `["deploy-timeline", name]`.
- Loading / empty (no segments) / partial states. Tests.

## Notes
- Per-deploy GitHub Actions + ECS-deployment calls are only for the detail page's current deploy —
  do NOT fan out across the fleet.
- History rows could get a timeline later (expandable) — out of scope for v1.
- Pairs with the live-rollout polling backlog item (rollout segment can update live while IN_PROGRESS).

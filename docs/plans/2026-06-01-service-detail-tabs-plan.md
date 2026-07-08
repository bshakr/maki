# Service-detail tabs (Deploys / Tasks / Metrics / Env) — implementation plan

**Goal:** Turn the single-scroll service detail page into four URL-driven tabs so a service's
deploys, running tasks, metrics, and env vars each get a focused view.

**Decisions (locked with user):**
- **Full-height tabs, no pinned card.** The current-deploy card lives inside the Deploys tab only
  (not pinned across tabs). More room per tab; live state is on the Deploys tab where it belongs.
- **URL-driven tabs** (shareable, reload-safe — matches the existing deep-link sheet pattern):
  - `/services/:name` → **Deploys** (default)
  - `/services/:name/deploys/:sha` → Deploys tab with the deploy-detail sheet open (existing route)
  - `/services/:name/tasks` → **Tasks**
  - `/services/:name/metrics` → **Metrics**
  - `/services/:name/env` → **Env**
- **Env is list-only** (read-only). No add/edit UI. Secrets show key + ARN ref, never a value.
- All AWS access stays **read-only**; Run task stays **preview-only/inert**.

**Tech stack:** React + shadcn `Tabs` + react-router-dom; FastAPI read-only endpoints; the
deploy-events store for metrics.

---

## Task 1 — Tab scaffold + routing (frontend only)

Convert `ServiceDetailPage` to a tabbed layout. Header (title + Refresh/Run task) stays; below it a
shadcn `Tabs` bar drives the active view. Active tab is derived from the URL path segment; clicking a
tab navigates. Deploys is default.

- Move the current `CurrentDeploySection` + `DeployHistory` into a `DeploysTab` component (the
  Deploys tab body). The deep-link sheet (`/deploys/:sha`) opens over the Deploys tab.
- Add `TasksTab`, `MetricsTab`, `EnvTab` as placeholders ("Coming next") for now; later tasks fill
  them. Remove the inline "Recent actions" placeholder card (folded into Tasks/Metrics intent).
- Routing in `App.tsx`: add `/services/:name/tasks|metrics|env`; keep `/services/:name` and
  `/services/:name/deploys/:sha`. The page reads the trailing segment to pick the tab.
- Tests: tab renders, default = Deploys, clicking a tab updates URL + content, deep-link to
  `/services/:name/metrics` opens on the Metrics tab, existing deploy-sheet deep-link still works.

## Task 2 — Metrics tab (per-service)

- `fetchMetrics({ service })` already exists. `MetricsTab` renders that service's deploy frequency,
  lead-time median, deploy count, and trend — scoped to the service. Reuse any metric tiles/charts
  from the global Metrics page.
- Backend: confirm metrics for a single service read from the deploy-events store (post-ingester),
  not the live fan-out; adjust the metrics service if still fanning out. Keep response schema.
- Tests: tab shows the service's numbers; loading + empty states.

## Task 3 — Tasks tab (read-only) + Run task

- Backend: `GET /api/services/:name/tasks` — `ecs.list_tasks(cluster, serviceName)` then
  `describe_tasks` (read-only). Return per task: task id (short), last status, health status,
  started-at, task-def revision, availability zone. Pydantic schema + SWR-cached service.
- Frontend: `TasksTab` lists running tasks (status pill, started-ago, revision) + the existing
  **Run task** trigger/sheet (still preview-only/inert).
- Tests: backend service maps describe_tasks output; frontend renders rows + empty state.

## Task 4 — Env tab (list-only, read-only)

- Backend: `GET /api/services/:name/env` — `describe_task_definition` for the service's current
  task def; return `containerDefinitions[].environment` (key/value) and `secrets[]` (key + valueFrom
  ARN ref — NEVER a secret value). Group by container if more than one. Schema + cached service.
- Frontend: `EnvTab` lists env key/value pairs and a separate "Secrets" group showing key + ref
  (with a copy-ref affordance). Clear "read-only" affordance; no edit controls.
- Tests: backend maps env + secret refs and never leaks a value; frontend renders both groups.

---

## Sequencing
Task 1 is the base (everyone stacks on it). Tasks 2/3/4 are independent of each other and can land in
any order on top of 1. Each task = its own ship-flow run + local commit; backend endpoints (Tasks/Env)
get their own commit ahead of their frontend consumer where it reads cleaner.

## Notes
- LOCAL ONLY: no push, no PR, no Linear. Commit locally only.
- Reuse existing patterns: SWR-cached services (`history/service.py`), the `HeaderActions` portal, the
  URL-driven sheet pattern from `ServiceDetailPage`.

# maki — System Architecture

A "Railway-like" deploy console: see what's deployed across the fleet, deploy
history + DORA metrics, and (preview-only) rollback / run-task — to speed up incident response.

**Status:** local prototype. Read-only against real
production AWS; all write/action surfaces are deliberately inert (see [Safety posture](#safety-posture)).

---

## 1. System context

```
        ┌────────────────────────── maki (single process) ──────────────────────────┐
 dev ──▶ │  FastAPI (uvicorn)  ──serves──▶  built React SPA (StaticFiles + fallback)  │
browser  │      │                                                                     │
         │      │   reads ──▶  Postgres deploy-events store (history/activity/metrics) │
         │      │   live  ──(boto3, READ-ONLY)──▶  AWS ECS  (current state: inventory)  │
         │      │                                                                       │
         │  background ingester (lifespan loop, every ~5m, READ-ONLY):                  │
         │      ├──(boto3)──▶  AWS ECS    (cluster "production", eu-west-1)              │
         │      ├──(boto3)──▶  AWS Amplify (web-app, app dexampleapp123)                  │
         │      ├──(httpx)──▶  GitHub REST API (commit author/msg/time)                  │
         │      └──upsert──▶   Postgres deploy-events store                              │
         └─────────────────────────────────────────────────────────────────────────────┘
```

- **Persisted in a dedicated Postgres "deploy-events" store (P2.5).** A background ingester is the sole
  AWS caller for deploy *history*: it snapshots ECS/Amplify, enriches via GitHub, and upserts events.
  History/Activity/Metrics read the store (instant, survives restarts, reaches past ECS's ~90-day
  retention). **Inventory (current live state) stays live** per request off ECS `describe_services`.
- **Credentials:** boto3 uses the ambient AWS identity (the developer's, locally). GitHub uses an
  optional `GITHUB_TOKEN` (`export GITHUB_TOKEN=$(gh auth token)`); without it, enrichment is skipped.
- **AWS API surface is exclusively list/describe/get** — no `update`, no `register`, no `run_task`,
  no dispatch anywhere in the codebase.

## 2. Runtime topology

- **Single process.** The container `ENTRYPOINT` is `uvicorn maki.main:app` — one worker, one event
  loop. No gunicorn, no `--workers`. So in-process state (the SWR cache, the background-refresh
  thread pool) is process-global and consistent; there is **no multi-worker write-contention concern
  today**. (This is the single most important fact for the DB decision below.)
- **One port (8787 in the container)** serves both `/api/*` and the SPA. The SPA catch-all route is
  registered AFTER the API routers, so `/api/*` and `/health` win; everything else falls back to
  `index.html` for client-side routing. Path traversal in the fallback is guarded.
- **Local dev** runs backend (uvicorn, `STATIC_DIR` unset → no SPA mount) and the Vite dev server
  separately; the container build bundles the SPA and sets `STATIC_DIR=/app/static`.

## 3. Backend architecture

Layered, one Python package per domain under `backend/src/maki/`:

```
api.py            FastAPI app; includes every domain router; mounts the SPA last (guarded)
main.py           re-exports `app` for uvicorn
settings.py       pydantic-settings (region, cluster, amplify ids, repo map, SWR windows, caps)
schemas.py        all pydantic response models (DeployedService, DeployRecord, …, MetricsResponse)
cache.py          SwrCache — stale-while-revalidate, in-process
github_enrich.py  GitHubEnricher — commit author/message/url/pr/committed_at via httpx (token-opt)

db/
  engine.py         SQLAlchemy engine + SessionLocal + get_session(); DATABASE_URL
  models.py         DeployEvent (the deploy-events table) + Base
  repository.py     DeployEventRepository — upsert_many + read queries (all SQL lives here)
  (migrations in backend/migrations, maki's own Alembic — plain venv, NOT pants)

ingest/
  service.py        DeployEventIngester (run_once: snapshot AWS → enrich → upsert) + build_ingester()
  loop.py           ingest_loop — async driver, runs run_once on a worker thread every interval

aws/
  clients.py        boto3 ecs_client() / amplify_client()
  ecs_registry.py   ECSDeployRegistry — currently-deployed services (list+describe, batched, fault-isolated)
  ecs_history.py    ECSDeployHistory — per-family deploy timeline from task-def revisions
  service_deployments AWSServiceDeployments — per-revision finishedAt (go-live) from ECS deployments
  amplify_registry  AmplifyDeployRegistry — current web-app deploy (get_branch + get_job)
  images.py         sha_from_image (image tag → git sha)

inventory/  service + routes  →  GET /api/services                      (LIVE — ECS describe_services)
history/    service + routes  →  GET /api/services/{name}/deployments    (reads deploy-events store)
activity/   service + routes  →  GET /api/activity                       (reads deploy-events store)
metrics/    service + routes  →  GET /api/metrics                        (reads store via history)
rollback/   routes            →  POST /api/services/{name}/rollback      (INERT preview)
run_task/   routes            →  POST /api/services/{name}/run-task       (INERT preview)
health_check.py               →  GET /health
```

**Pattern per domain:** a thin FastAPI router (`@cache`'d singleton factory wires dependencies) →
a `*Service` holding business logic + its own `SwrCache`. History/Activity/Metrics read the
deploy-events store via `DeployEventRepository`; Inventory reads ECS live; the ingester is the only
component that fans out to AWS for history. Each endpoint accepts `?refresh=1` to bypass the cache.
Services are constructed once via `functools.cache` so the cache persists for the process lifetime.
The ingester runs on a FastAPI **lifespan** task (gated by `ingest_enabled`), offloading each blocking
cycle to a worker thread; shutdown cancels it (no wedge on `--reload`).

**Fault isolation:** `ECSDeployRegistry` maps each service inside a try/except so one malformed
service becomes an `error:`/`unavailable:` row instead of sinking the whole dashboard.

## 4. Data sources — how each view is derived

| View | Source | Derivation |
|---|---|---|
| **Services** (`/api/services`) | **LIVE** — ECS `list_services`+`describe_services` (batched 10), Amplify `get_branch`+`get_job` | primary deployment → sha (from `containerDefinitions[0].image`), counts, rolloutState; web-app from Amplify active job |
| **Deploy history** (`/deployments`) | **deploy-events store** — `list_for_service(name, limit)` | newest-30 stored events → `DeployRecord` (incl. `finished_at`); already enriched by the ingester |
| **Activity** (`/activity`) | **deploy-events store** — `list_recent(limit)` | chronological fleet feed, newest go-live first (`COALESCE(finished_at, registered_at)`), multiple events per service |
| **Metrics** (`/metrics`) | **deploy-events store** via store-backed history | aggregate in-window events → deploy_count, deploys/day, median lead time (committed_at→registered_at), per-day trend; ECS-only |

- **git sha** = the image tag (`image.rsplit(":", 1)[-1]`), one container per task def.
- **History source of truth = the deploy-events store**, populated by the ingester from ECS task-def
  revisions + ECS service-deployment `finishedAt` (go-live) + GitHub enrichment. The store persists
  past ECS's ~90-day retention going forward.
- **Metrics read every in-window event from the store** (no per-request AWS fan-out, no revision cap —
  the old `metrics_max_revisions_per_service` cap under-counted busy services and is now gone).
- **Inventory stays live** so the current-deploy card reflects real-time status/task counts; the store
  (history/activity/metrics) lags by at most one ingest interval (~5 min).

## 5. Caching model

Two independent layers, **both volatile**:

1. **Backend — `SwrCache` (in-process, per service instance).** `get(key, loader, force)`:
   serve fresh (≤ `swr_fresh_seconds=10`); serve stale + single-flight background refresh on a
   `ThreadPoolExecutor` (≤ `swr_stale_seconds=300`); block-and-recompute when cold/too-stale/forced.
   Immutable cached records are `model_copy()`'d out so a background refresh can't race a response
   being serialized. **No eviction** — keys live for process lifetime (a known minor growth issue for
   the date-bucketed metrics keys; tracked in BACKLOG under precompute).
2. **Frontend — TanStack Query (in-browser).** `staleTime 10s`, `refetchInterval 15s`,
   refetch-on-focus, `retry 1`. Manual Refresh sets a one-shot flag → `?refresh=1`.

**Now backed by the deploy-events store (P2.5):** History/Activity/Metrics reads are a single indexed
SQL query against Postgres, fronted by the same `SwrCache`. Persistence survives restarts, so cold
reads are instant (no describe-per-revision fan-out, no GitHub enrich on the read path) — the ingester
does that work in the background and the store retains it. Only Inventory still computes live from ECS
per request (current state, intentionally).

## 6. Frontend architecture

- **React 19 + Vite + TypeScript**, `@/` → `src`. `react-router-dom` with 4 routes under a shared
  `Layout` (shadcn **sidebar-08**): Services `/`, Service detail `/services/:name`, Activity
  `/activity`, Metrics `/metrics`.
- **TanStack Query** for all server state (keys: `["services"]`, `["deployments", name]`,
  `["activity"]`, `["metrics", rangeDays, service]`).
- **shadcn/ui + Tailwind v4** (`@tailwindcss/vite`), zinc base, config-driven theme tokens, dark/light via a
  `ThemeProvider`. `recharts` (via shadcn chart) for the metrics trend.
- **Single API client** (`src/api.ts`) — typed fetch wrappers mirroring the backend schemas.
- **Actions** are dialogs/sheets: `rollback-dialog.tsx` (Dialog) and `run-task-sheet.tsx` (Sheet),
  both preview-only with a type-service-name-to-confirm gate.

## 7. Safety posture

Maki touches **real production** read-only. Two action surfaces exist in the UI but are **inert by
construction**:

- `POST /api/services/{name}/rollback` and `POST /api/services/{name}/run-task` each only build and
  return a `*Preview` model with `executed=False`. No ECS write, no `run_task`, no GitHub
  `workflow_dispatch`, no subprocess, no side effect. Verified by grep: the only matches for
  execution keywords are the safety comments and the route function names.
- The entire boto3 surface is list/describe/get. There is no code path that mutates AWS.
- Arming either action for real is deliberate future work with its own review — not a config flip.

## 8. Deployment

- **Multi-stage Dockerfile:** stage 1 (node:20) builds the SPA; stage 2 (python:3.11-slim) installs
  the API, copies the built SPA to `/app/static`, runs as non-root `maki`, `EXPOSE 8787`.
- **Ephemeral container filesystem** — no volume is mounted. Anything written to local disk does not
  survive a redeploy.
- **Intended hosting: a hosted, ephemeral container** (ECS/Fargate-style, no persistent local disk).
  No deploy target is committed yet (no ECS task def / Fargate service / compose / terraform for maki
  itself) — it runs locally via uvicorn today — but the ephemeral-container assumption is now fixed,
  which is why persistence lives in an **external** datastore (see §9), not on local disk.

## 9. Persistence — the DB decision

We want a **deploy ledger** to: (a) make reads instant via background precompute, (b) survive
restarts/redeploys, (c) reach history further back than live ECS retention, and (d) record actions
once they're armed — unlocking rollback count, change-fail rate, drift flag, and Actions run links.

### Requirements / workload shape
- **Write volume: very low.** A background ingester upserts deploy events every few minutes.
- **Read pattern: read-mostly, simple.** By service, by date range; the whole dataset (deploy events
  for a few dozen services) is small — thousands of rows, fits comfortably in memory.
- **Durability: must survive container redeploys** (ephemeral fs — see §8).
- **Concurrency: single process today**, but should not paint us into a corner if maki later runs
  multi-worker.
- maki is **already AWS-native** (ambient AWS creds, no other infra).

### Options

| Option | Durable on ephemeral fs? | Infra/ops | Multi-worker | Query power | Fit |
|---|---|---|---|---|---|
| **SQLite (file)** | ❌ only with a mounted EFS/EBS volume | none (local) / volume (hosted) | needs WAL + care | full SQL | great **locally**; weak hosted unless we add a volume |
| **Postgres** (reuse the org's existing) | ✅ | external dep, secrets, coupling | ✅ | full SQL | durable but **overkill + couples** a side tool to prod DB infra |
| **DynamoDB** | ✅ (serverless) | low (table + IAM); AWS-native | ✅ | key/range only (PK=service, SK=registered_at) | **strong** — durable, no disk, fits append-only deploy events, ~free at this volume |
| **S3 snapshot of in-memory state** | ✅ | minimal (one bucket/object) | ⚠️ writer races if multi-proc | none (load-all into memory) | **strong** for single-process + small dataset; simplest moving parts |

### Reading of the tradeoff
- **SQLite is the obvious local choice but a poor hosted one** here: the container fs is ephemeral, so
  durability needs an EFS/EBS volume (Fargate EFS mount = real added complexity), and a future
  multi-worker setup needs WAL discipline. SQLite shines when there's a stable disk and one writer —
  not guaranteed by maki's (undecided) hosting.
- **Postgres** is the safe heavyweight, but pulling a side tool into prod DB infra (connections,
  secrets, migrations, coupling) is disproportionate to a few thousand deploy rows.
- **DynamoDB** matches maki's profile best: AWS-native (creds already present), serverless (no disk
  or volume to manage, survives any redeploy), append-only deploy events map cleanly to a
  `PK=service, SK=registered_at` item model, on-demand billing is negligible at this volume, and it's
  multi-worker-safe out of the box.
- **S3 snapshot** is the minimalist play: keep the current in-memory architecture, periodically dump
  the computed per-service timeline to one object, load it on boot. Durable across restarts with
  almost no new code or infra — as long as maki stays single-process and the dataset stays
  memory-sized (both true today).

### Decision (2026-05-31): maki's own dedicated Postgres

**Chosen: a dedicated Postgres instance owned by maki** — a *separate* database, NOT the org's
production DB. Hosting is fixed as a **hosted, ephemeral container**, so persistence must be external
to the container; Postgres on its own instance is durable independent of redeploys.

Rationale:
- **Durable on an ephemeral fs** — the DB is external; container redeploys don't touch it.
- **Multi-worker-safe** out of the box — no SQLite WAL/volume gymnastics; we can scale workers freely.
- **Full SQL** suits the upcoming queries (date-range metric aggregates, drift live-vs-ledger joins,
  action audit) far better than DynamoDB's key/range model or an S3 load-all snapshot.
- **A dedicated instance avoids the coupling concern** that made reusing the org's prod DB unattractive
  (no shared connections/secrets/migration lanes with production).

Implications for implementation (P2.5):
- Add **SQLAlchemy + Alembic** to the standalone backend (plain venv — maki runs its own alembic,
  NOT pants/monorepo tooling). Migrations live in the backend; generate skeletons, never handwrite.
- Connection via a `DATABASE_URL` setting (pydantic-settings); local dev gets a Postgres service in a
  `docker compose` file in the repo; tests run against a disposable/transactional DB (or a SQLite/PG
  test fixture — decide at plan time).
- The **background ingester** upserts deploy events (idempotent on `service+revision`); metrics,
  history, and activity reads repoint to the store; the per-request AWS fan-out is dropped (the
  ingester becomes the only AWS caller). Precompute folds into the ingester.

### Status (2026-06-01): IMPLEMENTED — "deploy-events store"

P2.5 is built. We call it the **deploy-events store** (table `deploy_events`), not "ledger" (the table
upserts/mutates rows as enrichment lands, so it isn't a strict append-only ledger).

- **Task 1** — `db/` package (SQLAlchemy models + repository + engine), maki's own Alembic, a
  `maki-postgres` service in `docker-compose.yml`, `DATABASE_URL` (port 5544 local). ✓
- **Task 2** — `DeployEventIngester` + `ingest_loop` on a FastAPI lifespan (gated by `ingest_enabled`,
  cancel-on-shutdown). Per-service watermark (`max(registered_at) − overlap`), 90-day cold-start
  backfill, failure isolation, idempotent upsert. Unique constraint is `NULLS NOT DISTINCT` so the
  single revision-NULL Amplify row per service upserts instead of duplicating. ✓
- **Task 3** — History/Activity read the store; Metrics rides on store-backed History; Inventory stays
  live. The `metrics_max_revisions_per_service` cap (which under-counted busy services) is removed. ✓
- **Task 4** — this doc + BACKLOG update; no dead AWS code (the read modules are reused by the
  ingester + live inventory). ✓
- Tests use a dedicated `<db>_test` database so a running maki instance can't leak rows into the suite.

## 10. Known limitations / tech debt

- History/Activity/Metrics lag live state by up to one ingest interval (~5 min); the current-deploy
  card stays live (Inventory). Acceptable for history-type views; Refresh forces a recompute.
- The ingester's cold-start backfill (empty store) is heavy (90 days × all services × GitHub enrich)
  and can exhaust the GitHub hourly quota — the tail of a first run may land un-enriched until later
  cycles fill it. Steady-state cycles are cheap (per-service watermark).
- `SwrCache` has no eviction (date-bucketed metrics keys grow slowly in a long-running process).
- Frontend bundle > 500 kB (recharts) — code-split candidate.
- Amplify excluded from metrics (no revision timeline); it does appear in the activity feed.
- Global service search is the ⌘K command palette (`command-menu.tsx`); the fleet grid has its own text filter.
- GitHub enrichment is rate-limited without a token; lead time is null when commit time is unknown.

## 11. Roadmap pointers

P1 visibility ✓ · P2 history+activity ✓ · caching ✓ · P3 rollback ✓ (inert) · P5 metrics ✓
(real-only) · P4 run-task ✓ (inert) · **P2.5 persistence (deploy-events store + ingester) ✓**. The
store now unblocks the deferred work: drift flag (live ECS vs store), Actions run links, action audit
records (rollback count / change-fail), and lead time past ECS's 90-day window. Also in flight:
service-detail tabs (Deploys/Tasks/Metrics/Env — scaffold ✓). See `docs/BACKLOG.md` and `docs/plans/`.

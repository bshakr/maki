# maki — project guide for coding agents

maki is a deploy console for AWS fleets: one dashboard showing what's deployed across every
service, with deploy history, durations, DORA-style metrics, logs, env, and a one-off task
runner — built to make incident response and deploy management less painful.

## The one safety invariant: reads are live, writes are fake

maki points at **real production AWS** and the **real GitHub API**, both read-only. Every
"action" that would mutate prod is deliberately a **preview that performs no side effect**:

- `POST /services/{name}/rollback` returns a `RollbackPreview` — no ECS update, no deploy.
- `POST /services/{name}/run-task` returns a `RunTaskPreview` — no `ecs:RunTask`, no dispatch,
  no subprocess, nothing.

When extending these, keep them side-effect-free unless the maintainer *explicitly* asks to wire
up real execution. Never add a write call to AWS or GitHub on your own initiative.

## Repo layout

```
maki/
  backend/             # FastAPI app — pyproject.toml, requirements*.txt, src/maki/, tests/, migrations/
  frontend/            # React + Vite SPA
  docs/                # plan.md, ARCHITECTURE.md, BACKLOG.md, ideas/, plans/
  docker-compose.yml   # maki's own Postgres (port 5544)
  Makefile             # bootstrap + dev orchestration: make setup / dev / doctor / check / update
  AGENTS.md  README.md  LICENSE  .gitignore
```

Run backend commands from `backend/`, frontend commands from `frontend/`.
`make check` from the repo root is the full gate: ruff + eslint + tsc + pytest + vitest.

## Stack

- **Backend** — Python 3.11, FastAPI, uvicorn, boto3, httpx, pydantic-settings, SQLAlchemy +
  alembic. Plain venv + `requirements.txt`; this is a standalone app with no external shared
  libraries.
- **Frontend** — React 19 + Vite + TypeScript, Tailwind v4, shadcn/ui on a **sidebar-08** layout
  with react-router and react-query. shadcn components live in `frontend/src/components/ui/*`
  (generated — don't hand-edit), the app shell in `frontend/src/components/`, pages in
  `frontend/src/pages/`. `@/` aliases `frontend/src`. Reach for a shadcn component before
  hand-rolling a UI primitive.

## Configuration

All deployment-specific values (AWS region/cluster, optional Amplify app, GitHub repo mapping,
branding/theme) live in the repo-root `maki.config.yaml` — gitignored, created from
`maki.config.example.yaml`. Never hardcode an account id, cluster name, or repo slug in source;
it belongs in the config layer. Operational knobs are env vars (see `backend/src/maki/settings.py`).

## Data sources

- **AWS (read-only)** via boto3 — uses the identity of the shell that started the backend; no
  profile baked in, no credentials written. Perms used: `sts:GetCallerIdentity`,
  `ecs:ListServices`/`DescribeServices`/`DescribeTaskDefinition`/`DescribeTasks`,
  `amplify:GetBranch`/`GetJob`, `cloudwatch:GetMetricData`.
- **GitHub API (read-only)** via `GITHUB_TOKEN` — Actions workflow runs (deploy timelines) plus
  commit/PR metadata (history enrichment). Repo mapping comes from `github.repos` in the config.
  Token is optional — calls degrade to empty without it — but unauthenticated requests hit
  GitHub's anonymous rate limit, so set one.
- **maki's own Postgres** (`localhost:5544`, via docker-compose) — a background ingester records
  deploy events into it; history and metrics read from it. Separate from any production database.

## What's built

Read-only visibility plus preview-only actions, all live against prod:

- Fleet board — every ECS service + the optional Amplify app: current SHA, deploy time,
  running/desired counts, rollout status (`GET /api/services`).
- Per-service deploy history and CI deploy timelines, resolvable down to a single deploy by
  short-sha (`/services/{name}/deployments`, `/deploy-timeline`, `/deploys/{sha}`).
- DORA-style metrics, activity feed, per-service env, logs, and task history.
- Rollback and run-task **previews** (see the safety invariant above).
- Identity panel — the assumed AWS caller, or a clear "credentials missing/expired" 503.

See `docs/plan.md`, `docs/ARCHITECTURE.md`, and `docs/BACKLOG.md` for context and what's next.

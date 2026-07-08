# maki — backend

FastAPI service behind the maki deploy console. Talks to **live production AWS** (read-only) via
boto3 and returns deploy state for every ECS service plus the optional Amplify app. The account,
region, cluster, and Amplify app are configured in the repo-root `maki.config.yaml` (see
[Config](#config-required)).

## Prerequisites

- Python 3.11
- AWS credentials for your account with **read** access to ECS **and Amplify** (if configured).
  Required actions: `ecs:ListServices`, `ecs:DescribeServices`, `ecs:DescribeTaskDefinition`,
  `amplify:GetBranch`, `amplify:GetApp`, `amplify:GetJob`.

  > ⚠️ If `GET /api/services` errors on the Amplify lookup, your role is likely missing
  > `amplify:GetBranch`/`amplify:GetJob`. Use a profile with Amplify read access.

## Setup (one-time)

> The easy path is `make setup` from the repo root (does all of this plus Postgres, migrations, and
> the frontend). The steps below are the manual backend-only equivalent.

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # runtime + pytest/ruff
pip install -e .                      # makes `maki` importable (uvicorn needs this)
```

`pip install -e .` is required — without it `uvicorn maki.api:app` fails with
`ModuleNotFoundError: No module named 'maki'` (the package lives under `src/`).

## Docker build lockfile

The Docker image installs from `requirements.lock.txt` (hash-pinned, `pip install --require-hashes`),
not `requirements.txt` — local dev keeps floating on `requirements-dev.txt` floors by design.

Regenerate the lock after editing `requirements.txt` **inside a container matching the
Dockerfile's Python base image** — compiling on macOS misses Linux-only conditional deps (e.g.
SQLAlchemy's `greenlet` marker), which then breaks `--require-hashes` at Docker build time:

```bash
cd backend
docker run --rm -v "$(pwd):/work" -w /work python:3.11.12-slim bash -c \
  "pip install --quiet pip-tools && pip-compile --generate-hashes --strip-extras -o requirements.lock.txt requirements.txt"
```

## Database (deploy ledger)

maki has its **own dedicated Postgres** (separate from any production database), used for the deploy ledger.
Start it via the repo-root `docker-compose.yml` and apply migrations with maki's own alembic
(plain venv — NOT pants/monorepo tooling):

```bash
# from the repo root
docker compose up -d maki-postgres        # postgres:16 on localhost:5544

# from backend/ with the venv active
alembic upgrade head                       # create the deploy_events table
```

Connection is configured via `DATABASE_URL` (see Configuration below); it defaults to the local
compose service on port **5544** (chosen to avoid clashing with any Postgres on 5432).

Generate new migrations with autogenerate (never handwrite the revision):

```bash
alembic revision --autogenerate -m "describe change"
```

The DB tests (`tests/db/`) require this Postgres to be up — they do **not** skip when the DB is
absent.

## AWS credentials

Any standard boto3 credential source works — an SSO helper like [Granted](https://granted.dev)
(`assume <your-profile>`), `aws sso login`, or exported keys:

```bash
assume <your-profile>   # SSO login if token stale; exports AWS_PROFILE + region into this shell
```

With SSO, boto3 resolves the token from the on-disk cache — no static keys are exported, that's
expected. Creds live only in the shell where you obtained them; run uvicorn in the same shell.

## Config (required)

The backend **won't start** without `maki.config.yaml` — all deployment-specific values
(AWS account, ECS/Amplify ids, GitHub repos) live there. It's shared with the frontend, so it
lives at the **repo root** (one level up from `backend/`), not under `backend/`. It's gitignored;
create it from the example:

```bash
# from the repo root
cp maki.config.example.yaml maki.config.yaml   # then edit
```

maki finds the repo-root `maki.config.yaml` automatically whether you launch from the repo root
or from `backend/` — **no env var needed**. Set `MAKI_CONFIG` only to point at a config elsewhere.

A missing or malformed config fails fast with a clear message pointing at
`maki.config.example.yaml` — never a raw traceback.

## Run

```bash
# Loopback-only by default; --reload via MAKI_RELOAD=1.
MAKI_RELOAD=1 python -m maki.server
```

See the root README "Security" section for the auth token and bind options.

Use port **8787** — the frontend Vite dev server proxies `/api` to `http://localhost:8787`
(see `frontend/vite.config.ts`). Running on another port means the SPA can't reach the API.

| URL | What |
|-----|------|
| http://localhost:8787/api/services | ECS services + Amplify web app deploy state |
| http://localhost:8787/health | liveness probe → `{"status": "ok"}` |
| http://localhost:8787/docs | Swagger UI |

In dev the SPA is **not** served by FastAPI — run the Vite dev server in `frontend/` instead.

## Tests / lint

```bash
pytest          # pythonpath=src is set in pyproject.toml
ruff check .
ruff format .
```

## Configuration

**Deployment-specifics** (AWS region/cluster, Amplify app, GitHub repo mapping, timeline tuning)
come from `maki.config.yaml` — see [Config](#config-required) above, not env vars.

**Operational knobs** load from env vars / a `.env` file in `backend/` (see `src/maki/settings.py`):

| Var | Default | Notes |
|-----|---------|-------|
| `MAKI_CONFIG` | repo-root `maki.config.yaml` (auto-found) | override only to use a config elsewhere; the repo-root file is found automatically from either the repo root or `backend/` |
| `DATABASE_URL` | `postgresql+psycopg://maki:maki@localhost:5544/maki` | maki's dedicated Postgres (deploy ledger) |
| `GITHUB_TOKEN` | unset | read-only GitHub token for deploy timelines + commit/PR enrichment; calls degrade to empty without it |
| `GITHUB_API_URL` | `https://api.github.com` | override for GitHub Enterprise |
| `SWR_FRESH_SECONDS` | `10` | serve cached `/api/services` as-is within this window |
| `SWR_STALE_SECONDS` | `300` | serve stale + refresh in the background up to this bound |
| `STATIC_DIR` | unset | point at built SPA to serve it from FastAPI (container/demo); leave unset in dev |
| `INGEST_ENABLED` | `true` | background deploy-event ingester (only runs under an ASGI server) |
| `INGEST_INTERVAL_SECONDS` | `300` | one ingest cycle every 5 minutes |
| `INGEST_BACKFILL_DAYS` | `90` | cold-start window (bounded by ECS ~90d retention) |
| `INGEST_OVERLAP_SECONDS` | `3600` | re-read this slice past the watermark each cycle |
| `INGEST_MAX_REVISIONS_PER_SERVICE` | `1000` | safety cap on per-service fan-out |

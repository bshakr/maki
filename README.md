# maki

A deploy console for AWS fleets — one dashboard to see what's deployed across your ECS services
(and an optional Amplify app), deploy history/duration, DORA-style metrics, and rollback/run-task
previews. Built to make incident response and deploy management easier.

> **Reads are live, writes are fake.** maki reads **live production AWS** (read-only) and the
> GitHub API. Every "action" (rollback, run-task) is a **preview that performs no side effect** —
> no ECS update, no task dispatch. See `AGENTS.md` for the design invariant.

> **⚠️ Security — run it on localhost only.** maki has **no auth** and serves live production read
> data. `GET /api/services/{name}/env` returns the **actual values** of plain environment variables
> (not just their names) — these frequently hold secrets. Anyone who can reach the port can read the
> whole fleet's env. Running `uvicorn` directly is safe (it binds `127.0.0.1` by default). If you
> containerise it, the process binds `0.0.0.0` inside the container — publish to host loopback only
> (`-p 127.0.0.1:8787:8787`). **Do not expose the port; add auth + a reverse proxy before any remote
> hosting.**

## What it does

A FastAPI backend live-queries AWS (ECS + Amplify) and the **GitHub API** (Actions runs + commit/PR
metadata for deploy timelines and history enrichment), and a background ingester records deploy
events into its own Postgres; a React + Vite SPA renders the fleet board, per-service deploy
history, DORA-style metrics, env, rollback/run-task previews, and the activity feed.

- **Backend**: Python 3.11, FastAPI, uvicorn, boto3, httpx, pydantic-settings, SQLAlchemy + alembic.
- **Frontend**: React 19, Vite, TypeScript, Tailwind v4, shadcn/ui, react-query, react-router.
- **AWS** (read-only): region, ECS cluster, and the optional Amplify app are set in
  `maki.config.yaml` (see [Configuration](#configuration)).
- **GitHub API** (read-only): Actions workflow runs + commit/PR metadata via `GITHUB_TOKEN`. Which
  repo each service deploys from is configured under `github.repos` in `maki.config.yaml`.

## Repo layout

```
maki/
  backend/             # FastAPI app: pyproject.toml, requirements*.txt, src/maki/, tests/, migrations/
  frontend/            # React + Vite SPA
  docs/                # plan.md, ARCHITECTURE.md, BACKLOG.md, ideas/, plans/
  docker-compose.yml   # maki's own Postgres (port 5544)
  Makefile             # bootstrap + dev orchestration: make setup / dev / doctor / test
```

## Port map

| Thing                | URL / port              |
|----------------------|-------------------------|
| Frontend (Vite dev)  | http://localhost:5173   |
| Backend (uvicorn)    | http://localhost:8787   |
| maki Postgres        | localhost:5544          |

The Vite dev server proxies `/api/*` → `http://localhost:8787`, so you load the app on **:5173**
and it talks to the backend on **:8787** transparently.

## Prerequisites

- **Node** (for the frontend; whatever recent LTS your nvm/asdf provides) + npm.
- **Python 3.11** (the backend venv is built against 3.11).
- **Docker** (for maki's local Postgres).
- **AWS access** in the shell that starts the backend (any standard boto3 credential source —
  e.g. Granted's `assume`, `aws sso login`, exported keys). maki has no AWS identity of its own;
  it acts as *your* identity.
- **GitHub token** — a `GITHUB_TOKEN` (a PAT with read access to the repos your services deploy
  from, or `gh auth token`) for deploy-timeline and history enrichment. Strictly optional —
  without it those calls just return empty — but anonymous requests hit GitHub's low rate limit,
  so set one. See below.

## Configuration

All deployment-specific values live in one ingested file, **`maki.config.yaml`** (gitignored — it
carries infra identifiers). Copy the committed example and fill it in:

```bash
cp maki.config.example.yaml maki.config.yaml   # then edit
```

Only the `aws` block is **required** (`region`, `ecsCluster`) — they point maki at real infra and
have no sensible default. Everything else is optional and falls back to a neutral default: GitHub
repo mapping (`github.repos`), the optional Amplify app (`amplify`, off by default), branding
(`branding.appName`), the shadcn theme overrides (`theme` — omit for vanilla), service grouping
(`grouping.rules`), the env-label pill (`envLabel`), and deploy-timeline tuning (`deployTimeline`).
Every field is documented inline in `maki.config.example.yaml`.

Keep `maki.config.yaml` at the **repo root** — it's shared between the backend and frontend. maki
finds it automatically whether the backend is launched from the repo root or from `backend/`; point
`MAKI_CONFIG` at another path only to override. The SPA fetches the UI-relevant subset from
`GET /api/config` at boot, so
one build serves any deployment — no rebuild to re-brand. A missing or invalid config fails fast at
startup with a message naming the offending field.

## Security

maki is read-only against live prod and has **no auth by default**. It's built to run locally for a
single operator. The posture, in order of importance:

- **Loopback-only by default.** `python -m maki.server` binds `127.0.0.1`; the kernel drops off-box
  packets. Binding a non-loopback interface requires `MAKI_ALLOW_NETWORK_BIND=1` (a deliberate
  opt-in). Never expose maki to the public internet.
- **Docker:** the container binds `0.0.0.0` (required), so publish to host loopback only —
  `docker run -p 127.0.0.1:8787:8787 …`. Anything else exposes live prod read data, including
  plaintext env-var values.
- **Host-header allowlist.** Requests must target `localhost`/`127.0.0.1` (defeats DNS-rebinding).
  Add proxy hostnames via `MAKI_ALLOWED_HOSTS=host1,host2`.
- **Optional shared token.** On a shared/multi-user box, set `MAKI_AUTH_TOKEN` (e.g.
  `openssl rand -hex 32`). Every `/api/*` call then needs `Authorization: Bearer <token>`; the SPA
  prompts for it once and stores it in origin-scoped localStorage. Unset on a personal laptop.

| Env var | Default | Purpose |
|---------|---------|---------|
| `MAKI_AUTH_TOKEN` | unset (no auth) | shared bearer token; set on a shared box |
| `MAKI_ALLOW_NETWORK_BIND` | `0` | opt-in to bind a non-loopback interface |
| `MAKI_ALLOWED_HOSTS` | _(loopback only)_ | extra Host-header values (proxy hostnames), comma-separated |
| `MAKI_HOST` / `MAKI_PORT` | `127.0.0.1` / `8787` | launcher bind address/port |
| `MAKI_NOTIFY_ENABLED` | `1` | deploy notifications for watched services; `0` silences them |
| `MAKI_BASE_URL` | `http://127.0.0.1:8787` | where a notification (and the CLI) reaches your maki |

## How AWS credentials flow (read this first)

maki calls live AWS as **whatever identity is in the shell that started the backend**. There's
no profile baked in and no credential file written — it uses the standard boto3 chain, which
picks up the env vars `assume` exports.

Concretely:

1. In a terminal, run **`assume`** (Granted) and pick the prod profile. This exports temporary
   AWS credentials **into that shell only**.
2. Start `uvicorn` **in that same shell** so it inherits those creds.
3. When the assumed session expires (typically ~1h), the backend's AWS calls start failing —
   maki surfaces this as a clear **"AWS credentials missing or expired"** panel (HTTP `503`
   with `error: aws_credentials_unavailable`). To recover: re-run `assume` in that shell and
   **restart uvicorn there**. A new shell without `assume` will not have creds.

The sidebar account block shows the assumed identity (`sts:GetCallerIdentity` → account id +
role/session name); when creds are absent it reads "No AWS identity".

## GitHub access

maki reads the **GitHub API** to enrich deploys with their CI timeline (Actions workflow runs)
and commit/PR metadata. It reads the token from the `GITHUB_TOKEN` env var — easiest is to pipe in
`gh auth token` in the backend's shell:

```bash
export GITHUB_TOKEN="$(gh auth token)"
```

The token needs **read** access to the repos configured under `github.repos` in
`maki.config.yaml`. Without a token, every GitHub call degrades to empty (timelines/enrichment
just stay blank) and any unauthenticated request is subject to GitHub's low anonymous rate
limit — so set one.

## Quickstart

### One command (from the repo root)

```bash
make setup        # idempotent: venv, backend + frontend deps, config, Postgres, migrations
assume <your-profile>                    # AWS creds into THIS shell (e.g. Granted) — make can't do this for you
export GITHUB_TOKEN="$(gh auth token)"   # optional: deploy timelines + commit/PR enrichment
make dev          # backend (:8787) + frontend (:5173) together; Ctrl-C stops both
```

Then open **http://localhost:5173**. `make` only auto-does the safe, idempotent steps — anything
that needs your interactive shell (`assume`) or a daemon (Docker) is **printed as the exact command
to run**, never run for you, and never hard-fails the build (creds are needed at request time, not
to boot). Run `make help` for all targets; **`make doctor`** prints a one-line health check per
dependency (config, venv, deps, Docker, Postgres, migrations, AWS creds, GitHub token) and names the
fix for anything missing — start here when something isn't working. **`make update`** pulls the
latest and re-runs `make setup`.

The manual steps below are what `make setup` / `make dev` run under the hood; reach for them only to
do something `make` doesn't cover.

### 1. Start Postgres (from the repo root)

```bash
docker compose up -d maki-postgres   # Postgres 16 on localhost:5544
```

### 2. Backend (from `backend/`)

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

# Config (required): create maki.config.yaml at the REPO ROOT from the example, then edit it.
# (From backend/: `cp ../maki.config.example.yaml ../maki.config.yaml`.) The backend won't start
# without it, but finds the repo-root file automatically — no MAKI_CONFIG needed.

# Apply migrations (creates the deploy-events tables in maki's Postgres):
alembic upgrade head

# Get AWS creds INTO THIS SHELL, then start the server in THIS SAME SHELL:
assume                                # pick the prod profile
export GITHUB_TOKEN="$(gh auth token)"  # for deploy timelines + commit/PR enrichment
# Start the server (loopback-only by default; the bind guard refuses non-loopback without opt-in):
MAKI_RELOAD=1 python -m maki.server
# → http://localhost:8787/api/services
# → http://localhost:8787/api/identity   (shows the assumed caller identity)
```

### 3. Frontend (from `frontend/`, in a separate terminal)

```bash
cd frontend
npm install
npm run dev          # Vite dev server on http://localhost:5173, proxies /api → :8787
```

Open **http://localhost:5173**.

### Deploy notifications

Opt a service into macOS notifications for its deploys (success, failure, and failed CI deploy
jobs):

```bash
maki watch insights
maki watches
maki unwatch insights
```

`make setup` installs the CLI into the backend venv, so either add `backend/.venv/bin` to your PATH
or alias it: `alias maki="$PWD/backend/.venv/bin/maki"`. The manual setup above installs only the
dependencies — run `make setup` (or `pip install -e .` in the venv) for the `maki` entrypoint,
including on an existing checkout that predates it. It talks to a running backend over the same
`/api/watches` endpoints the dashboard's Watch button uses — set `MAKI_BASE_URL` if yours isn't on
the default `http://127.0.0.1:8787`, and `MAKI_AUTH_TOKEN` if you've set a shared token.

Notifications are delivered by `terminal-notifier` when installed (`brew install
terminal-notifier`, which makes them clickable) and fall back to `osascript`.

ECS rollout notifications need no `GITHUB_TOKEN`. CI-failure notifications do: without one the
watcher skips the CI scan entirely, because polling GitHub unauthenticated every 45s would burn
the 60-requests/hour anonymous limit and blank the deploy timelines with it.

## Tests

```bash
make test                                  # backend pytest + frontend vitest (from the repo root)
```

Or directly:

```bash
# Backend (from backend/, venv active). Needs the local Postgres up (test DB is created on demand).
cd backend && pytest                       # whole suite
pytest tests/identity tests/aws            # a subset

# Frontend (from frontend/)
cd frontend && npm run test                # vitest run (one-shot)
npx vitest run src/components/nav-user.test.tsx   # a single file
npx tsc -b                                 # typecheck
```

## Required AWS permissions (read-only)

`sts:GetCallerIdentity`, `ecs:ListServices`, `ecs:DescribeServices`, `ecs:DescribeTaskDefinition`,
`ecs:DescribeTasks`, `amplify:GetBranch`, `amplify:GetJob`, plus `cloudwatch:GetMetricData`.
(GitHub read access is separate — via `GITHUB_TOKEN`, see [GitHub access](#github-access).)

## Troubleshooting

**Run `make doctor` first** — it checks every dependency (config, venv, deps, Docker, Postgres,
migrations, AWS creds, GitHub token) and prints the fix for whatever's red. The cases below are what
it points you to.

- **"AWS credentials missing or expired" panel / `503 aws_credentials_unavailable`** — your
  assumed session lapsed (or you started uvicorn in a shell that never ran `assume`). Re-run
  `assume` in the backend's shell and restart `uvicorn` there. Verify with
  `curl localhost:8787/api/identity` — it should return your account id and name, not a 503.
- **Sidebar shows "No AWS identity"** — same cause: no usable creds. Same fix.
- **Deploy timelines / commit-PR info are blank, or GitHub calls 403** — no `GITHUB_TOKEN` in the
  backend's shell (calls degrade to empty), or you hit GitHub's anonymous rate limit. Export
  `GITHUB_TOKEN="$(gh auth token)"` in that shell and restart `uvicorn`.
- **`uvicorn: command not found` / `ModuleNotFoundError: maki`** — the venv isn't active, or you
  dropped `--app-dir src`. Activate `.venv` and run from `backend/`.
- **Backend boots but every call 503s immediately** — you likely started it in a fresh shell.
  Creds live only in the shell where you ran `assume`; uvicorn must run there too.
- **DB connection refused on :5544 / migrations fail** — Postgres isn't up. Run
  `docker compose up -d maki-postgres` from the repo root, then `alembic upgrade head`.
- **Port 5173 or 8787 already in use** — stop the other process, or change the port
  (`--port` for uvicorn; Vite will offer the next free port automatically).

## License

[MIT](LICENSE)

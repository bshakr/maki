# Makefile bootstrap — plan

**Date:** 2026-06-19
**Source spec:** `docs/plans/2026-06-10-setup-dx-notes.md` (the doctor check table + bootstrap targets).
**Scope:** A root `Makefile` only — the *shell-level* `make doctor`, `make setup`, `make dev`. The
Python `maki.doctor` module, boot-time advisory, and friendly-503-on-DB-down path are OUT OF SCOPE
(separate brainstorm).

## Design principles

- **Reads are auto, user-shell steps are printed.** `make setup` does only safe idempotent things.
  Anything needing the user's interactive shell (`assume` → AWS creds) or a daemon (Docker not
  running) is **detected and printed as an exact command**, never run for the user. Absent creds
  must NOT fail the build — creds are needed only at request time, not to boot.
- **`make doctor` is a report:** one friendly ✓/✗ line per check, always exit 0.
- Idempotent throughout; `make setup` run twice is clean.
- No new heavyweight deps. `make dev` uses backgrounded processes + `trap 'kill 0'`.

## Paths / commands (from research, not guessed)

- venv: `backend/.venv`, built with `python3.11 -m venv`. Python pinned 3.11 (`requires-python>=3.11`).
- backend deps: `backend/.venv/bin/pip install -r requirements-dev.txt` (pulls in `requirements.txt`)
  **and** `pip install -e .` (required — without it `maki` isn't importable for `python -m maki.server`).
- config: repo-root `maki.config.yaml`, copy from `maki.config.example.yaml` **only if absent**.
- postgres: `docker compose up -d maki-postgres` (service `maki-postgres`, `postgres:16`, host port 5544).
- migrate: from `backend/`, venv active, `alembic upgrade head` (env.py reads `DATABASE_URL`).
- frontend deps: `frontend/`, `npm ci` if `package-lock.json` present else `npm install`.
- backend run: from `backend/`, `MAKI_RELOAD=1 .venv/bin/python -m maki.server` (loopback :8787).
- frontend run: from `frontend/`, `npm run dev` (Vite :5173, proxies `/api` → :8787).
- health: `GET http://localhost:8787/health` → `{"status":"ok"}` (no AWS creds needed).
- assume (printed, never run): `assume Nory/Developer` — Granted shell alias; Nory/Developer (NOT
  ReadOnly, which lacks `amplify:GetBranch`). After it: `export GITHUB_TOKEN="$(gh auth token)"`.

## Doctor checks (from the notes' table)

| Check | Healthy | Unhealthy line |
|-------|---------|----------------|
| Config file | `maki.config.yaml` exists | "copy maki.config.example.yaml → maki.config.yaml (run: make config)" |
| Docker daemon | `docker info` ok | "Docker daemon not running — start Docker Desktop / OrbStack" |
| Postgres :5544 | `nc -z 127.0.0.1 5544` | "ledger DB unreachable — run: make db-up" |
| Migrations | `alembic current` == head | "migrations pending — run: make migrate" |
| AWS creds | `aws sts get-caller-identity` ok | "AWS creds missing/expired — run: assume Nory/Developer (in your shell, then restart the backend there)" |
| GITHUB_TOKEN | env set OR `gh auth token` works | "GITHUB_TOKEN unset — timelines/PR enrichment empty (warning). export GITHUB_TOKEN=\"$(gh auth token)\"" |
| venv | `backend/.venv/bin/python` exists | "backend venv missing — run: make setup" |
| frontend deps | `frontend/node_modules` exists | "frontend deps missing — run: make setup" |

AWS + GITHUB_TOKEN are warnings (don't imply broken setup). Everything exits 0.

## Targets

| Target | Does |
|--------|------|
| `help` (default) | self-documenting list via `##` comments |
| `setup` | venv → backend-deps → config → db-up → migrate → frontend-deps; then prints next-steps (assume) |
| `dev` | backend + frontend concurrently, `trap 'kill 0'` cleanup; preflights creds and prints assume hint |
| `doctor` | the report above |
| `venv` | create `backend/.venv` if absent |
| `backend-deps` | pip install requirements-dev + `-e .` |
| `frontend-deps` | npm ci/install |
| `config` | copy example → real if absent |
| `db-up` | `docker compose up -d maki-postgres` (guarded: if docker down, print how to start it) |
| `migrate` | `alembic upgrade head` (guarded: if DB down, point at `make db-up`) |
| `backend` | run backend alone |
| `frontend` | run frontend alone |
| `test` | backend pytest + frontend vitest |
| `clean` | remove venv + node_modules (does NOT touch the postgres volume / config) |

## Cred-detection-and-print mechanism

A small make function `check-aws` runs `aws sts get-caller-identity` quietly; on failure it prints
the exact `assume Nory/Developer` line and continues (return 0). `make dev` calls it as advisory
before launching (boot doesn't need creds). `make db-up` similarly guards `docker info`. No target
fails solely because creds/docker are absent except `migrate`, which genuinely needs the DB.

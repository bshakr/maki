# Setup DX — Notes & Pickup (deferred follow-up)

**Date:** 2026-06-10
**Status:** Bootstrap piece SHIPPED 2026-06-19 (root `Makefile` + shell-level `make doctor`; see
`docs/plans/2026-06-19-makefile-bootstrap-plan.md`). **Still deferred:** the Python `maki.doctor`
module, boot-time advisory banner, and the friendly-503-on-DB-down path (open questions below).
**Context:** `docs/plans/2026-06-09-security-posture-design.md` carried a "Setup ergonomics (DX)"
section; we shipped layers 1–4 + logging + docs and **deferred the DX work** so we could brainstorm
it properly first. This file captures it so it isn't lost.

## Why

Setup is hand-typed README steps today — no Makefile, no script. The 7-step dance (venv → pip →
copy config → `assume` in the right shell → `GITHUB_TOKEN` → `docker compose up` → `alembic
upgrade`) fails cryptically when a step is missed. **The headline case:** maki's Postgres ledger
container down → ledger-backed endpoints (`/deployments`, `/metrics`, history) return an opaque
`500`, not "start the DB". This actually bit us (2026-06-09) — the deploy/metrics views all broke;
root cause was `maki-postgres` exited, surfaced only as `ECONNREFUSED`/`500`. Goal: engineers don't
burn time on setup, and failures explain themselves.

## The two pieces (proposed in the security design, not yet built)

### 1. Doctor / preflight
A check that runs on backend boot **and** as a standalone command (`python -m maki.doctor` or
similar). Validates each dependency, prints a friendly actionable line per check instead of a
traceback:

| Check | Healthy | Unhealthy message |
|-------|---------|-------------------|
| Config file | found + valid | "config not found — copy `maki.config.example.yaml` to `maki.config.yaml`" |
| AWS creds | caller identity resolves | "AWS creds missing/expired — run `assume`, then restart in the same shell" |
| Postgres (`:5544`) | reachable | "ledger DB unreachable at 127.0.0.1:5544 — run `docker compose up -d maki-postgres`" |
| Migrations | at head | "migrations pending — run `alembic upgrade head`" |
| `GITHUB_TOKEN` | set | "GITHUB_TOKEN unset — deploy timelines + PR/commit enrichment will be empty" (warning, not fatal) |

It would also report the live **security posture** (bind address, Host allowlist, token on/off) —
so it doubles as the startup banner (Project B dropped a standalone banner in favour of this).

On boot: **advisory** (log warnings, don't block startup) except where the app genuinely can't run
(invalid config already fails fast). The DB-down case → clear boot log line + a friendly `503`-with-
guidance on ledger-backed endpoints instead of an opaque `500`.

### 2. One-command bootstrap
A `Makefile` (and/or `scripts/setup.sh`) at the repo root:
- `make setup` — venv, `pip install -r requirements-dev.txt`, copy config from example (if absent),
  start `maki-postgres`, `alembic upgrade head`, install frontend deps.
- `make dev` — run backend + frontend together.
- `make doctor` — run the preflight check.

Turns the dance into `make setup && make dev`.

## Open questions to brainstorm (why this is deferred, not just built)

- **Doctor placement:** boot-time advisory vs a separate command vs both? How loud on boot?
- **The DB-down → 503 path:** where to intercept (per-route dependency? a DB-health gate?) so the
  ledger-backed endpoints degrade gracefully without scattering try/except everywhere.
- **`make` vs `just` vs a `scripts/` shell script** — what fits a standalone OSS repo best, and
  cross-platform (mac/linux) concerns. The monorepo uses `pants`/`just`; maki is plain venv.
- **`make dev` orchestration** — backend + frontend + postgres in one command without a process
  manager dependency. `concurrently`? `foreman`/`honcho`? a trivial `&` + trap? 
- **How much to auto-do vs prompt** — `make setup` copying config / starting docker silently vs
  asking. Smooth-but-not-surprising.
- **Interaction with `assume`** — creds must be in the launching shell; `make dev` can't inject
  them. Doctor should detect + guide rather than try to fix.

## Pointers
- Security posture (shipped): `docs/plans/2026-06-09-security-posture-design.md` (its "Setup
  ergonomics" section is the origin of this).
- The Postgres-down incident: deploy/metrics/history 500 when `maki-postgres` is stopped; fix was
  `docker compose up -d maki-postgres`. A doctor would have named it immediately.
- Pick up via the brainstorming skill → design → plan → ship, same as Projects A and B.

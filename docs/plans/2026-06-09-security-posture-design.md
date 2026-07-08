# Project B — Security Posture: Design

**Date:** 2026-06-09
**Status:** Design approved. Implementation plan to follow (`writing-plans`).
**Supersedes:** the scoping stub `docs/plans/2026-06-06-security-posture-notes.md` (kept for history).

---

## Goal

Make maki **safe-by-default for a localhost single operator**, and **defensible** the moment it
lands on a shared box or someone fat-fingers a network publish — without adding setup friction for
the common case. Review the posture, then implement the fixes. All local (no push), read-only
(the safety invariant holds — Project B adds **no** write path to AWS or GitHub).

## Threat model

One operator, on their own machine, running maki against their own assumed AWS credentials. maki is
**read-only**, so auth here protects **confidentiality of the HTTP surface**, not the integrity of
AWS (it cannot — maki runs with the operator's own identity; app auth only gates the HTTP layer).

The realistic threats, in order:

1. **Accidental network exposure** — a `--host 0.0.0.0`, a `-p 8787:8787` (all interfaces), a shared
   host or bastion. Turns a local tool into a full-fleet deploy-state + plaintext-env endpoint
   reachable off-box.
2. **Browser-borne local attacks** — a malicious website the operator visits fires requests at
   `http://localhost:8787`. Plain cross-origin reads are already blocked by the browser's
   same-origin policy (maki sends no CORS headers). **DNS-rebinding** defeats SOP and is *not*
   blocked today.
3. **Other local users / processes** on a shared machine — loopback binding does not distinguish
   "me" from "another user/process on the same box."
4. **Secrets coming to rest in logs** — a separate exfil path from the live surface; logs persist
   and get shipped to aggregators.

Out of scope: real per-user auth / OIDC, any write/execute path, payload encryption (see "Rejected"
below).

---

## The env-values decision (Option 0 — keep the feature)

`GET /api/services/{name}/env` returns each container's inline `environment` as `[{name, value}]`
in **plaintext**, plus `secrets` as refs (`value_from` ARN only — maki never resolves them). Seeing
env values is a **kept feature** (diagnosing config drift between deploys is real, useful work).

The decision: **the access-control layers protect the values, not payload transformation.** No
redaction, no masking, no reveal flag, no `security:` block in `config.yaml`. The endpoint is
untouched. This is sound because:

- The operator already has AWS access to read these exact vars via the console — maki grants them
  nothing new.
- Layers 1–4 below gate *who can reach the endpoint*; off-box, TLS at a reverse proxy protects the
  wire. Those are the real controls.

### Rejected: payload encryption ("encrypt over the wire, decrypt in the app")

Encrypting the response and decrypting it in maki's own browser JS is **security theater**. For the
SPA to decrypt, the key must be reachable by whatever runs the page's JS — so any attacker who can
hit the endpoint can also obtain the key (from the bundle, another endpoint, or the bearer token).
The bar does not move. Payload encryption only helps when the decrypting party differs from every
possible attacker and holds a key the attacker cannot get (true end-to-end) — but maki's server *is*
the plaintext source, so there is no E2E to have. The legitimate "encrypt over the wire" is **TLS**,
which is a transport concern: on loopback there is no wire to protect; off-box it is the reverse
proxy's job. maki must not roll its own crypto.

---

## The layers (defense in depth)

All security configuration is **env-var driven**. Nothing security-related goes in `config.yaml`,
and **no secret is ever served to the SPA**.

### Layer 1 — Bind guard

**New:** `backend/src/maki/net_guard.py`.

maki refuses to start bound to a non-loopback interface unless `MAKI_ALLOW_NETWORK_BIND=1` is
explicitly set. Loopback (`127.0.0.1`, `::1`) → proceed. Any other host without the opt-in → exit
with a clear message naming the resolved host and the opt-in var.

Accidental network exposure becomes impossible; deliberate exposure requires a named action.

**Docker note:** inside a container maki *must* bind `0.0.0.0` (the container's own loopback is
unreachable from the host even with `-p`). So `docker-compose.yml` sets `MAKI_ALLOW_NETWORK_BIND=1`
**and** publishes to loopback (`127.0.0.1:8787:8787`) — the guard is satisfied deliberately, and the
real control (host publish scope) is the loopback mapping. The app is blind to the host `-p`
mapping; we ship the safe form as the default and document it.

### Layer 2 — Host-header allowlist

**`TrustedHostMiddleware`** in `backend/src/maki/api.py`. Allowed hosts: `localhost`, `127.0.0.1`,
`[::1]`, plus any extra from `MAKI_ALLOWED_HOSTS` (comma-separated, for the proxy case). A
DNS-rebind request arrives with `Host: evil.com` → rejected (400). ~5 lines.

### Layer 3 — CORS stays closed

No CORS middleware exists today, so the browser's same-origin policy already blocks cross-origin
reads. Keep it that way. Add a **regression test** asserting no response ever carries
`Access-Control-Allow-Origin: *`. No runtime code.

### Layer 4 — Bearer token (optional, off by default)

**New:** `backend/src/maki/auth.py`. Loaded via `MAKI_AUTH_TOKEN` in `settings.py` (next to
`github_token`). Unset/empty → auth disabled (the laptop default — zero friction). Set → enforced.

- Backend: middleware requires `Authorization: Bearer <token>` on `/api/*`. **Exempt:** the health
  endpoint, the SPA shell/static assets, and the `auth_required` flag on `/api/config` (so the SPA
  can discover that a login is needed and bootstrap the gate). **Constant-time** comparison
  (`hmac.compare_digest`).
- `/api/config` gains a non-secret boolean `auth_required` (true iff a token is set). It never
  carries the token itself.
- Frontend: on boot, if `auth_required` is true and no stored token, render a **login gate**
  (token-entry screen). Store the entered token in `localStorage` (origin-scoped — a malicious site
  on another origin cannot read it). `api.ts` attaches the `Authorization: Bearer` header on every
  request. A `401` clears the stored token and bounces back to the gate.

Generate a token with `openssl rand -hex 32`. Defensible as the only auth because maki is read-only.

---

## Logging hygiene

Today maki logs none of this (verified: no `logger` call in `service_env`; default uvicorn access
log is method/path/status only; no body-logging middleware; env values are never written to the
DB). The point is to make that an **explicit, guarded invariant** rather than a happy accident that
the next debug-logging line breaks.

1. **Never log request/response bodies.** Keep the access log at method/path/status. Documented as
   an invariant.
2. **Never log secrets.** The `Authorization` header, `MAKI_AUTH_TOKEN`, and `GITHUB_TOKEN` must
   never reach logs. The doctor (below) reports *presence* (`token: set`), never the value.
3. **Error paths don't leak.** Exception handlers log `type + message`, not response locals/bodies,
   so an env-path traceback cannot carry a value into a log.
4. **Guard it:** a test asserting no body-logging middleware is registered, and that doctor output
   masks token/secret values.

---

## Setup ergonomics (DX)

Setup is hand-typed README steps today (no Makefile, no script). The 7-step dance (venv → pip →
copy config → `assume` in the right shell → `GITHUB_TOKEN` → `docker compose up` → `alembic
upgrade`) fails cryptically when a step is missed — e.g. Postgres down surfaces as an opaque `500`,
not "start the DB". The goal: engineers don't burn time on setup.

### Doctor / preflight

**New:** a preflight check that runs on backend boot **and** as a standalone command
(`python -m maki.doctor` or equivalent). It validates each dependency and prints a friendly,
actionable line per check instead of a traceback:

| Check | Healthy | Unhealthy message |
|-------|---------|-------------------|
| Config file | found + valid | "config not found — copy `maki.config.example.yaml` to `maki.config.yaml`" |
| AWS creds | caller identity resolves | "AWS creds missing/expired — run `assume`, then restart in the same shell" |
| Postgres (`:5544`) | reachable | "ledger DB unreachable at 127.0.0.1:5544 — run `docker compose up -d maki-postgres`" |
| Migrations | at head | "migrations pending — run `alembic upgrade head`" |
| `GITHUB_TOKEN` | set | "GITHUB_TOKEN unset — deploy timelines + PR/commit enrichment will be empty" (warning, not fatal) |

It also reports the **live security posture** (bind address, Host allowlist, token on/off) — so it
doubles as the startup banner (no separate banner feature). It never prints secret *values*.

On boot the check is **advisory** (logs warnings, does not block startup) except where the app
genuinely cannot run (e.g. invalid config already fails fast). The DB-down case becomes a clear log
line on boot and a friendly `503`-with-guidance on the ledger-backed endpoints rather than an opaque
`500`.

### One-command bootstrap

**New:** a `Makefile` (and/or `scripts/setup.sh`) at the repo root:

- `make setup` — create venv, `pip install -r requirements-dev.txt`, copy `maki.config.example.yaml`
  → `maki.config.yaml` (if absent), start `maki-postgres`, run `alembic upgrade head`, install
  frontend deps.
- `make dev` — run backend + frontend together.
- `make doctor` — run the preflight check.

Turns the 7-step dance into `make setup && make dev`.

---

## Where configuration lives (the split that matters)

- **Secrets + posture → env / `.env` (gitignored), never `config.yaml`, never sent to the SPA:**
  `MAKI_AUTH_TOKEN`, `MAKI_ALLOW_NETWORK_BIND`, `MAKI_ALLOWED_HOSTS`.
- **`config.yaml`:** unchanged by Project B. No `security:` block (Option 0 left nothing non-secret
  to toggle).

Rationale: `config.yaml` has a committed example and a shared Nory template, and a subset of it is
served to the browser via `/api/config`. A secret in that file would be one mistake from being
committed or shipped to every client. maki already keeps operational secrets (`github_token`,
`database_url`) in env via `settings.py`; the auth token belongs with them.

---

## File map

**Backend — new:**
- `backend/src/maki/net_guard.py` — loopback bind guard.
- `backend/src/maki/auth.py` — bearer-token middleware + constant-time check.
- `backend/src/maki/doctor.py` — preflight checks + posture report; importable + `python -m`.

**Backend — modified:**
- `backend/src/maki/api.py` — register `TrustedHostMiddleware`, auth middleware, call doctor on boot.
- `backend/src/maki/settings.py` — `auth_token`, `allow_network_bind`, `allowed_hosts` from env.
- `backend/src/maki/app_config/routes.py` — add `auth_required` (bool) to the `/api/config` payload.
- ledger-backed routes / error handling — DB-down → friendly `503`, not `500`.

**Frontend — new:**
- `frontend/src/components/auth-gate.tsx` — token-entry login gate.
- token storage + header attach in `frontend/src/api.ts`; `auth_required` in `AppConfigResponse`.

**Frontend — modified:**
- boot/`ConfigProvider` — render the gate when `auth_required` and no stored token; clear + re-gate
  on 401.

**Repo root — new:**
- `Makefile` (+ optionally `scripts/setup.sh`).

**Docs:**
- `docker-compose.yml` — publish `127.0.0.1:8787:8787`, set `MAKI_ALLOW_NETWORK_BIND=1`.
- `README.md` — security section: threat model, the env vars, "when to set the token", the bind
  rule, `make setup`/`make dev`.

---

## Testing

- **Bind guard:** loopback host → starts; non-loopback without opt-in → refuses; opt-in → allows.
- **Host allowlist:** disallowed `Host` → 400; loopback `Host` → 200; `MAKI_ALLOWED_HOSTS` extends.
- **CORS regression:** no response carries `Access-Control-Allow-Origin: *`.
- **Bearer token:** unset → open; set → 401 without header / 200 with correct token; wrong token →
  401; comparison is constant-time (`hmac.compare_digest`); health + config-`auth_required` exempt.
- **Logging hygiene:** no body-logging middleware registered; doctor output masks token/secret
  values.
- **Doctor:** each check returns the right status + message; DB-down → friendly 503 on a
  ledger-backed endpoint (not 500).
- **Frontend:** gate renders when `auth_required` and no token; stored token attaches as Bearer
  header; 401 clears token and re-gates.

---

## Setup cost on a laptop (the smooth-setup guarantee)

Every security default is a no-op for the single-operator laptop:

| Layer | Setup steps (default) |
|-------|----------------------|
| Bind guard | none — loopback is the default |
| Host allowlist | none — loopback hosts baked in |
| CORS closed | none |
| Bearer token | none — off by default; the gate appears only if *you* set the token |
| Logging hygiene | none — invariants + tests |
| Doctor / bootstrap | **negative** — removes friction (`make setup && make dev`) |

The only operators who touch the token, bind guard, or Host list are those deliberately running on a
shared box — exactly when the extra care is warranted.

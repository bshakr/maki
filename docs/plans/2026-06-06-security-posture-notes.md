# Security Posture — Notes & Decisions (Project B stub)

**Date:** 2026-06-06
**Status:** Scoping notes only. Full Project B (security review + hardening) is separate from
Project A (config layer). Captured here so findings aren't lost.

## Findings (from code read)

### 1. `service_env` exposes plaintext environment VALUES (headline)
`GET /api/services/{name}/env` (no auth) returns, per container:
- `environment: [{ name, value }]` — plain env vars, **value returned verbatim**.
- `secrets: [{ name, value_from }]` — secret refs, **ARN only, never the value**.

maki never resolves secrets (no SSM/Secrets Manager call), so the `secrets` bucket is safe. The
exposure is the **plaintext `environment` values** — and inline env frequently holds DB URLs with
passwords, tokens, signing keys. Risk is conditional on the target service's config hygiene; maki
can't tell and echoes whatever's there.

**Already-good hygiene:** not cached (no plaintext retained in memory), never written to DB, never
logged, secrets refs-only. The gap is purely **access control + the inherent inline-value
exposure**.

### 2. No auth layer anywhere; binds `0.0.0.0:8787`
Anyone who reaches the port reads every service's plain env + full fleet deploy state, no creds.
Local-only today = fine; exposed (shared host, bastion, open container port) = full-fleet plain-env
exfil.

### 3. `/api/config` (added by Project A) widens the surface
Serves region / cluster / console-URL data unauthenticated. Not secret, but more surface. Project B
owns the posture.

## Decision: auth = Option A (localhost-only) for now

maki is **read-only** (actions inert by design) → auth protects **confidentiality**, not integrity.
Auth on maki does **not** protect AWS creds (it runs with the operator's own assumed identity; auth
only gates the HTTP surface).

**Chosen default: A — localhost-only, no app auth.** Bind `127.0.0.1`, document "do not expose."
For the single-operator local tool maki is today, this is correct; a login on a localhost app is
theater. Remote access via SSH port-forward / tunnel.

**Deferred escalations (document, don't build yet):**
- **C — optional shared bearer token** (`MAKI_AUTH_TOKEN`, ~20 lines, env-gated off): cheap middle
  for a small internal box. Defensible because read-only.
- **B — reverse proxy / identity-aware proxy** (Cloudflare Access / Tailscale / IAP / oauth2-proxy):
  recommended way to expose to a team. Make the app proxy-friendly (`X-Forwarded-*`).
- **D — full in-app OIDC:** avoid unless the inert actions ever go live (would add attack surface to
  a read-only tool).

If actions become real (breaking the safety invariant), the bar rises to real per-user auth + audit.

## Project A touchpoint (done)

Local `uvicorn` already binds `127.0.0.1` by default (safe). The **Dockerfile must keep `0.0.0.0`**
inside the container — binding `127.0.0.1` there makes the mapped port unreachable even with `-p`.
The real control for containers is host-side: publish to loopback only
(`-p 127.0.0.1:8787:8787`). Project A documents this in the Dockerfile + README and states the env
endpoint exposes **values, not just names**. Everything else here is Project B.

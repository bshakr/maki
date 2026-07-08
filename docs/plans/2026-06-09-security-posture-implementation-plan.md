# Project B — Security Posture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lock down maki's local HTTP surface — loopback bind guard, Host-header allowlist, CORS-closed regression guard, optional bearer token, and logging-hygiene invariants — keeping the env-values feature as-is and the laptop default zero-friction.

**Architecture:** All security config is env-var driven (`MAKI_*`), never in `config.yaml`, never sent to the SPA. A new launcher (`maki.server`) owns the bind and runs the guard before handing off to uvicorn. Middleware (`TrustedHostMiddleware`, an optional `BearerAuthMiddleware`) gate the HTTP layer. The SPA discovers `auth_required` from the already-exempt `/api/config`, shows a login gate, and attaches the token via a central `apiFetch` wrapper.

**Tech Stack:** Python 3.11, FastAPI/Starlette, pydantic-settings, uvicorn, pytest; React 19 + Vite + TS, vitest.

**Scope:** Layers 1–4 + logging hygiene + docs from `docs/plans/2026-06-09-security-posture-design.md`. **Setup DX (doctor + bootstrap) is explicitly deferred** to a follow-up.

**Run context:** backend commands from `backend/` with the venv active (`source .venv/bin/activate` or call `.venv/bin/python`/`.venv/bin/pytest` directly). maki uses plain `pytest` (NOT pants). A live local Postgres is required for the suite (`docker compose up -d maki-postgres`). Frontend commands from `frontend/` (`npm test`).

---

## File Structure

**Backend — new:**
- `backend/src/maki/net_guard.py` — pure bind-safety check (`is_loopback`, `assert_safe_bind`, `NetworkBindError`). No I/O.
- `backend/src/maki/server.py` — launcher: resolve host/port from env, run the guard, call `uvicorn.run("maki.main:app", …)`. Runnable via `python -m maki.server`.
- `backend/src/maki/auth.py` — `BearerAuthMiddleware` + `is_auth_exempt`. Constant-time token compare.

**Backend — modified:**
- `backend/src/maki/settings.py` — add `auth_token`, `allow_network_bind`, `allowed_hosts` (env aliases); `auth_required` + `trusted_hosts` properties.
- `backend/src/maki/api.py` — register `TrustedHostMiddleware` always, `BearerAuthMiddleware` when a token is set.
- `backend/src/maki/schemas.py` — add `auth_required: bool` to `UiConfigResponse`.
- `backend/src/maki/app_config/routes.py` — populate `auth_required` from settings.
- `backend/tests/conftest.py` — allow the TestClient `Host: testserver` during the suite.

**Frontend — new:**
- `frontend/src/lib/auth-token.ts` — `getAuthToken`/`setAuthToken`/`clearAuthToken` (localStorage, key `maki-auth-token`).
- `frontend/src/components/auth-gate.tsx` — login gate + 401 re-gate.

**Frontend — modified:**
- `frontend/src/api.ts` — `apiFetch` wrapper (attaches Bearer, fires `maki:unauthorized` on 401); route all `/api` calls through it; add `auth_required` to `AppConfigResponse`.
- `frontend/src/components/config-provider.tsx` — add `auth_required: false` to `DEFAULT_APP_CONFIG`.
- `frontend/src/App.tsx` — wrap content in `<AuthGate>`.

**Docs:**
- `Dockerfile` — switch entrypoint to the launcher; refresh the no-auth comment for the token.
- `README.md` + `backend/README.md` — security section + new run command.

---

## Task 1: Settings — security env fields

**Files:**
- Modify: `backend/src/maki/settings.py`
- Test: `backend/tests/test_settings_security.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_settings_security.py
from maki.settings import Settings


def test_auth_disabled_by_default():
    s = Settings()
    assert s.auth_token is None
    assert s.auth_required is False


def test_auth_token_from_env(monkeypatch):
    monkeypatch.setenv("MAKI_AUTH_TOKEN", "sekret")
    s = Settings()
    assert s.auth_token == "sekret"
    assert s.auth_required is True


def test_trusted_hosts_defaults_to_loopback():
    s = Settings()
    assert s.trusted_hosts == ["localhost", "127.0.0.1", "[::1]"]


def test_trusted_hosts_extends_with_env(monkeypatch):
    monkeypatch.setenv("MAKI_ALLOWED_HOSTS", "maki.internal, box.lan")
    s = Settings()
    assert s.trusted_hosts == ["localhost", "127.0.0.1", "[::1]", "maki.internal", "box.lan"]


def test_allow_network_bind_from_env(monkeypatch):
    monkeypatch.setenv("MAKI_ALLOW_NETWORK_BIND", "1")
    assert Settings().allow_network_bind is True
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_settings_security.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'auth_token'`.

- [ ] **Step 3: Implement**

In `backend/src/maki/settings.py`, add the import and the fields/properties.

Add to the imports at the top:
```python
from pydantic import Field
```

Add these fields inside `class Settings` (after `ingest_max_revisions_per_service`):
```python
    # --- Security posture (env-only; never in config.yaml, never served to the SPA) ---
    # Optional shared bearer token. Unset/empty → auth disabled (the laptop default). Aliased so the
    # env var is the explicit MAKI_AUTH_TOKEN, not the bare field name.
    auth_token: str | None = Field(default=None, validation_alias="MAKI_AUTH_TOKEN")
    # Opt-in to bind a non-loopback interface (the launcher's bind guard checks this).
    allow_network_bind: bool = Field(default=False, validation_alias="MAKI_ALLOW_NETWORK_BIND")
    # Extra Host-header values to allow beyond loopback (comma-separated), for a reverse-proxy host.
    allowed_hosts: str = Field(default="", validation_alias="MAKI_ALLOWED_HOSTS")
```

Add these properties (after `repo_for`):
```python
    @property
    def auth_required(self) -> bool:
        """True when a bearer token is configured, i.e. the SPA must present one."""
        return bool(self.auth_token)

    @property
    def trusted_hosts(self) -> list[str]:
        """Allowed Host-header values: loopback always, plus any from MAKI_ALLOWED_HOSTS."""
        extra = [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]
        return ["localhost", "127.0.0.1", "[::1]", *extra]
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_settings_security.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/src/maki/settings.py backend/tests/test_settings_security.py
git commit -m "feat(security): add auth-token + bind/host settings (env-only)"
```

---

## Task 2: Bind guard (`net_guard.py`)

**Files:**
- Create: `backend/src/maki/net_guard.py`
- Test: `backend/tests/test_net_guard.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_net_guard.py
import pytest

from maki.net_guard import NetworkBindError, assert_safe_bind, is_loopback


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "[::1]", "127.5.5.5"])
def test_loopback_hosts_recognised(host):
    assert is_loopback(host) is True


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.10", "maki.internal", ""])
def test_non_loopback_hosts(host):
    assert is_loopback(host) is False


def test_loopback_bind_allowed():
    assert_safe_bind("127.0.0.1", allow_network_bind=False)  # no raise


def test_non_loopback_refused_without_optin():
    with pytest.raises(NetworkBindError) as exc:
        assert_safe_bind("0.0.0.0", allow_network_bind=False)
    assert "0.0.0.0" in str(exc.value)
    assert "MAKI_ALLOW_NETWORK_BIND" in str(exc.value)


def test_non_loopback_allowed_with_optin():
    assert_safe_bind("0.0.0.0", allow_network_bind=True)  # no raise
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_net_guard.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'maki.net_guard'`.

- [ ] **Step 3: Implement**

```python
# backend/src/maki/net_guard.py
"""Loopback bind guard.

maki has no auth by default and serves live prod read data (incl. plaintext env-var values), so it
must not be reachable off-box by accident. Binding a loopback address is an OS-level guarantee that
off-box packets are dropped. This guard refuses any non-loopback bind unless the operator opts in
with MAKI_ALLOW_NETWORK_BIND=1 (e.g. inside a container, where 0.0.0.0 is required and the real
control is the host publish scope).
"""

import ipaddress

_LOOPBACK_NAMES = {"localhost"}


class NetworkBindError(RuntimeError):
    """Raised when maki would bind a non-loopback interface without an explicit opt-in."""


def is_loopback(host: str) -> bool:
    """True if ``host`` is a loopback name or address. IPv6 brackets are tolerated (``[::1]``)."""
    h = host.strip().strip("[]")
    if h in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def assert_safe_bind(host: str, *, allow_network_bind: bool) -> None:
    """Raise NetworkBindError if ``host`` is non-loopback and the network-bind opt-in is off."""
    if is_loopback(host) or allow_network_bind:
        return
    raise NetworkBindError(
        f"refusing to bind {host!r}: not a loopback address. maki has no auth by default and "
        "serves live prod read data. To bind a non-loopback interface deliberately, set "
        "MAKI_ALLOW_NETWORK_BIND=1 (and front it with auth or a trusted proxy)."
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_net_guard.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/maki/net_guard.py backend/tests/test_net_guard.py
git commit -m "feat(security): loopback bind guard"
```

---

## Task 3: Launcher (`server.py`) + switch entrypoints

**Files:**
- Create: `backend/src/maki/server.py`
- Test: `backend/tests/test_server_launcher.py` (create)
- Modify: `Dockerfile`

- [ ] **Step 1: Write the failing test**

The launcher must run the guard before binding and pass the resolved host/port to uvicorn. Patch `uvicorn.run` so the test never starts a server.

```python
# backend/tests/test_server_launcher.py
import pytest

from maki import server
from maki.net_guard import NetworkBindError


def test_main_defaults_to_loopback(monkeypatch):
    calls = {}
    monkeypatch.setattr(server.uvicorn, "run", lambda *a, **k: calls.update(args=a, kw=k))
    monkeypatch.delenv("MAKI_HOST", raising=False)
    monkeypatch.delenv("MAKI_PORT", raising=False)
    monkeypatch.delenv("MAKI_ALLOW_NETWORK_BIND", raising=False)
    server.main()
    assert calls["args"] == ("maki.main:app",)
    assert calls["kw"]["host"] == "127.0.0.1"
    assert calls["kw"]["port"] == 8787


def test_main_refuses_non_loopback_without_optin(monkeypatch):
    monkeypatch.setattr(server.uvicorn, "run", lambda *a, **k: None)
    monkeypatch.setenv("MAKI_HOST", "0.0.0.0")
    monkeypatch.delenv("MAKI_ALLOW_NETWORK_BIND", raising=False)
    with pytest.raises(NetworkBindError):
        server.main()


def test_main_allows_non_loopback_with_optin(monkeypatch):
    calls = {}
    monkeypatch.setattr(server.uvicorn, "run", lambda *a, **k: calls.update(kw=k))
    monkeypatch.setenv("MAKI_HOST", "0.0.0.0")
    monkeypatch.setenv("MAKI_ALLOW_NETWORK_BIND", "1")
    server.main()
    assert calls["kw"]["host"] == "0.0.0.0"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_server_launcher.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'maki.server'`.

- [ ] **Step 3: Implement**

```python
# backend/src/maki/server.py
"""maki's supported launch entrypoint: ``python -m maki.server``.

Owns the bind so the loopback guard runs before any socket is opened. Host/port/reload come from
the environment (defaults: 127.0.0.1:8787, reload off). uvicorn imports the app from the
``maki.main:app`` import string, so this module never imports the app itself.
"""

import os

import uvicorn

from maki.net_guard import assert_safe_bind


def _env_bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def main() -> None:
    host = os.environ.get("MAKI_HOST", "127.0.0.1")
    port = int(os.environ.get("MAKI_PORT", "8787"))
    reload = _env_bool("MAKI_RELOAD")
    assert_safe_bind(host, allow_network_bind=_env_bool("MAKI_ALLOW_NETWORK_BIND"))
    uvicorn.run("maki.main:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_server_launcher.py -v`
Expected: PASS.

- [ ] **Step 5: Switch the Dockerfile entrypoint to the guarded launcher**

In `Dockerfile`, replace the final `ENTRYPOINT` line and add the opt-in env (a container must bind `0.0.0.0`; the real control is publishing to host loopback). Replace:
```dockerfile
ENTRYPOINT ["uvicorn", "maki.main:app", "--host", "0.0.0.0", "--port", "8787"]
```
with:
```dockerfile
# Inside a container maki must bind 0.0.0.0 (binding 127.0.0.1 here would make the mapped port
# unreachable even with -p), so the bind guard's network opt-in is set deliberately. The real
# exposure control is the HOST publish scope — publish to loopback only: `-p 127.0.0.1:8787:8787`.
# maki has no auth unless MAKI_AUTH_TOKEN is set; keep it off the public internet regardless.
ENV MAKI_ALLOW_NETWORK_BIND=1 MAKI_HOST=0.0.0.0 MAKI_PORT=8787
ENTRYPOINT ["python", "-m", "maki.server"]
```

- [ ] **Step 6: Verify the image still builds**

Run: `docker build -t maki-test . && echo OK`
Expected: build succeeds, prints `OK`. (Skip if Docker is unavailable; note it in the task report.)

- [ ] **Step 7: Commit**

```bash
git add backend/src/maki/server.py backend/tests/test_server_launcher.py Dockerfile
git commit -m "feat(security): guarded launch entrypoint (python -m maki.server)"
```

---

## Task 4: Host-header allowlist (TrustedHostMiddleware)

**Files:**
- Modify: `backend/src/maki/api.py`
- Modify: `backend/tests/conftest.py`
- Test: `backend/tests/test_trusted_host.py` (create)

> **Why the conftest change:** Starlette's `TestClient` sends `Host: testserver` by default. With the allowlist active, every existing test would get `400`. Allowing `testserver` **only in the suite** (via the env the allowlist already reads) keeps all 14 inline `TestClient(app)` call sites working with zero edits, while production stays loopback-only.

- [ ] **Step 1: Allow `testserver` during the suite**

In `backend/tests/conftest.py`, next to the existing `MAKI_CONFIG` `setdefault` (before any `maki` import), add:
```python
# TrustedHostMiddleware rejects unknown Host headers; the TestClient sends "testserver". Allow it
# for the suite only (real runs never set this), so route tests keep their bare TestClient(app).
os.environ.setdefault("MAKI_ALLOWED_HOSTS", "testserver")
```

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/test_trusted_host.py
from fastapi.testclient import TestClient

from maki.api import app


def test_allowed_host_passes():
    client = TestClient(app)  # Host: testserver, allowed via conftest
    assert client.get("/health").status_code == 200


def test_disallowed_host_rejected():
    client = TestClient(app, headers={"host": "evil.example.com"})
    r = client.get("/health")
    assert r.status_code == 400


def test_loopback_host_allowed():
    client = TestClient(app, headers={"host": "127.0.0.1"})
    assert client.get("/health").status_code == 200
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_trusted_host.py -v`
Expected: FAIL — `test_disallowed_host_rejected` gets `200` (no allowlist yet).

- [ ] **Step 4: Implement**

In `backend/src/maki/api.py`, add the import near the other FastAPI imports:
```python
from starlette.middleware.trustedhost import TrustedHostMiddleware
```

Immediately after `register_aws_error_handlers(app)` (and before the `include_router` calls), add:
```python
# Reject requests whose Host header isn't loopback (or an explicitly-allowed proxy host). Defends
# against DNS-rebinding, where a malicious site resolves to 127.0.0.1 to bypass the same-origin
# policy. Loopback hosts are always allowed; MAKI_ALLOWED_HOSTS adds proxy hostnames.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_trusted_host.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Run the full backend suite to confirm no Host regressions**

Run: `cd backend && .venv/bin/pytest -q`
Expected: PASS (all existing tests still green — `testserver` is allowed in the suite).

- [ ] **Step 7: Commit**

```bash
git add backend/src/maki/api.py backend/tests/conftest.py backend/tests/test_trusted_host.py
git commit -m "feat(security): Host-header allowlist (anti DNS-rebind)"
```

---

## Task 5: CORS-closed regression guard

**Files:**
- Test: `backend/tests/test_cors_closed.py` (create)

> No runtime code — maki sends no CORS headers today (verified). This test locks that in so a future `CORSMiddleware(allow_origins=["*"])` can't slip in unnoticed.

- [ ] **Step 1: Write the test**

```python
# backend/tests/test_cors_closed.py
from fastapi.testclient import TestClient

from maki.api import app


def test_no_wildcard_cors_on_simple_get():
    client = TestClient(app)
    r = client.get("/health")
    assert r.headers.get("access-control-allow-origin") != "*"


def test_no_cors_headers_on_cross_origin_preflight():
    client = TestClient(app)
    r = client.options(
        "/api/config",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    # With no CORS middleware, there is no permissive allow-origin echoing the attacker origin.
    assert r.headers.get("access-control-allow-origin") not in ("*", "https://evil.example.com")
```

- [ ] **Step 2: Run to verify it passes immediately**

Run: `cd backend && .venv/bin/pytest tests/test_cors_closed.py -v`
Expected: PASS (this is a guard, not a red-then-green change).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_cors_closed.py
git commit -m "test(security): assert CORS stays closed (no wildcard allow-origin)"
```

---

## Task 6: Bearer-token middleware (`auth.py`)

**Files:**
- Create: `backend/src/maki/auth.py`
- Modify: `backend/src/maki/api.py`
- Test: `backend/tests/test_auth_middleware.py` (create)

- [ ] **Step 1: Write the failing test**

Test the middleware as a unit on a minimal app (so it's independent of the global settings singleton).

```python
# backend/tests/test_auth_middleware.py
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maki.auth import BearerAuthMiddleware, is_auth_exempt


def _app(token: str) -> FastAPI:
    app = FastAPI()

    @app.get("/api/secret")
    def secret():
        return {"ok": True}

    @app.get("/api/config")
    def config():
        return {"auth_required": True}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    app.add_middleware(BearerAuthMiddleware, token=token)
    return app


def test_exempt_paths():
    assert is_auth_exempt("/health") is True
    assert is_auth_exempt("/api/config") is True
    assert is_auth_exempt("/assets/app.js") is True  # non-/api → SPA shell
    assert is_auth_exempt("/api/services") is False


def test_protected_path_401_without_token():
    client = TestClient(_app("sekret"))
    assert client.get("/api/secret").status_code == 401


def test_protected_path_200_with_correct_token():
    client = TestClient(_app("sekret"), headers={"Authorization": "Bearer sekret"})
    assert client.get("/api/secret").status_code == 200


def test_protected_path_401_with_wrong_token():
    client = TestClient(_app("sekret"), headers={"Authorization": "Bearer nope"})
    assert client.get("/api/secret").status_code == 401


def test_exempt_paths_reachable_without_token():
    client = TestClient(_app("sekret"))
    assert client.get("/health").status_code == 200
    assert client.get("/api/config").status_code == 200
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_auth_middleware.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'maki.auth'`.

- [ ] **Step 3: Implement**

```python
# backend/src/maki/auth.py
"""Optional shared-bearer-token gate for the HTTP surface.

Enabled only when MAKI_AUTH_TOKEN is set (off by default — the laptop case needs no auth). When on,
every /api/* request must carry ``Authorization: Bearer <token>``; the health check, the SPA shell
and assets, and /api/config (so the SPA can discover auth is required and show its login gate) are
exempt. The token is never logged and never sent to the client.
"""

import hmac

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

_EXEMPT_PATHS = {"/health", "/api/config"}


def is_auth_exempt(path: str) -> bool:
    """True for paths reachable without a token: health, the config bootstrap, and the SPA shell."""
    if path in _EXEMPT_PATHS:
        return True
    return not path.startswith("/api/")


class BearerAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, token: str) -> None:
        super().__init__(app)
        self._token = token

    async def dispatch(self, request: Request, call_next):
        if is_auth_exempt(request.url.path):
            return await call_next(request)
        header = request.headers.get("authorization", "")
        scheme, _, presented = header.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(presented, self._token):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_auth_middleware.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Wire it into the app (conditionally)**

In `backend/src/maki/api.py`, add the import:
```python
from maki.auth import BearerAuthMiddleware
```

Right after the `TrustedHostMiddleware` line added in Task 4, add:
```python
# Optional shared-token gate. Off unless MAKI_AUTH_TOKEN is set (laptop default = no auth).
if settings.auth_token:
    app.add_middleware(BearerAuthMiddleware, token=settings.auth_token)
```

- [ ] **Step 6: Confirm the suite stays green (auth off by default)**

Run: `cd backend && .venv/bin/pytest -q`
Expected: PASS — no token set in the suite, so the gate is inert and existing route tests are unaffected.

- [ ] **Step 7: Commit**

```bash
git add backend/src/maki/auth.py backend/src/maki/api.py backend/tests/test_auth_middleware.py
git commit -m "feat(security): optional bearer-token gate (off by default)"
```

---

## Task 7: Expose `auth_required` on `/api/config`

**Files:**
- Modify: `backend/src/maki/schemas.py`
- Modify: `backend/src/maki/app_config/routes.py`
- Modify: `backend/tests/test_app_config.py`
- Test: same file

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_app_config.py`:
```python
def test_config_reports_auth_not_required_by_default():
    client = TestClient(app)
    body = client.get("/api/config").json()
    assert body["auth_required"] is False
```

(If `app`/`TestClient` aren't already imported in that file, add `from fastapi.testclient import TestClient` and `from maki.api import app`.)

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_app_config.py::test_config_reports_auth_not_required_by_default -v`
Expected: FAIL — `KeyError: 'auth_required'`.

- [ ] **Step 3: Implement**

In `backend/src/maki/schemas.py`, add a field to `class UiConfigResponse` (after `deploy_timeline_enabled`):
```python
    auth_required: bool = False
```

In `backend/src/maki/app_config/routes.py`, set it in `ui_config_from`. Change the `return UiConfigResponse(` block to include:
```python
        deploy_timeline_enabled=cfg.deployTimeline.enabled,
        auth_required=settings.auth_required,
```
(`settings` is already imported in that module.)

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_app_config.py -v`
Expected: PASS (existing config tests + the new one).

- [ ] **Step 5: Commit**

```bash
git add backend/src/maki/schemas.py backend/src/maki/app_config/routes.py backend/tests/test_app_config.py
git commit -m "feat(security): surface auth_required on /api/config"
```

---

## Task 8: Frontend token store + `apiFetch` wrapper

**Files:**
- Create: `frontend/src/lib/auth-token.ts`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/components/config-provider.tsx`
- Test: `frontend/src/lib/auth-token.test.ts` (create), `frontend/src/api.test.ts` (create)

- [ ] **Step 1: Write the failing tests**

```typescript
// frontend/src/lib/auth-token.test.ts
import { afterEach, expect, test } from "vitest";

import { clearAuthToken, getAuthToken, setAuthToken } from "@/lib/auth-token";

afterEach(() => clearAuthToken());

test("returns null when unset", () => {
  expect(getAuthToken()).toBeNull();
});

test("round-trips through localStorage", () => {
  setAuthToken("sekret");
  expect(getAuthToken()).toBe("sekret");
});

test("clear removes it", () => {
  setAuthToken("sekret");
  clearAuthToken();
  expect(getAuthToken()).toBeNull();
});
```

```typescript
// frontend/src/api.test.ts
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { apiFetch } from "@/api";
import { clearAuthToken, setAuthToken } from "@/lib/auth-token";

beforeEach(() => clearAuthToken());
afterEach(() => {
  clearAuthToken();
  vi.restoreAllMocks();
});

test("attaches the Bearer header when a token is set", async () => {
  setAuthToken("sekret");
  const spy = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(new Response("{}", { status: 200 }));
  await apiFetch("/api/services");
  const init = spy.mock.calls[0][1] as RequestInit;
  expect(new Headers(init.headers).get("Authorization")).toBe("Bearer sekret");
});

test("sends no Authorization header when no token", async () => {
  const spy = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(new Response("{}", { status: 200 }));
  await apiFetch("/api/services");
  const init = spy.mock.calls[0][1] as RequestInit;
  expect(new Headers(init.headers).get("Authorization")).toBeNull();
});

test("clears token and dispatches maki:unauthorized on 401", async () => {
  setAuthToken("stale");
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("", { status: 401 }));
  const onUnauth = vi.fn();
  window.addEventListener("maki:unauthorized", onUnauth);
  await apiFetch("/api/services");
  window.removeEventListener("maki:unauthorized", onUnauth);
  expect(onUnauth).toHaveBeenCalled();
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd frontend && npm test -- --run auth-token api`
Expected: FAIL — module `@/lib/auth-token` and export `apiFetch` not found.

- [ ] **Step 3: Implement the token store**

```typescript
// frontend/src/lib/auth-token.ts
// The optional bearer token (set only when the backend has MAKI_AUTH_TOKEN). Stored in
// localStorage, which is origin-scoped: a malicious site on another origin cannot read it.
const KEY = "maki-auth-token";

export function getAuthToken(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function setAuthToken(token: string): void {
  localStorage.setItem(KEY, token);
}

export function clearAuthToken(): void {
  localStorage.removeItem(KEY);
}
```

- [ ] **Step 4: Implement `apiFetch` and route calls through it**

In `frontend/src/api.ts`, add the import at the top:
```typescript
import { clearAuthToken, getAuthToken } from "@/lib/auth-token";
```

Add the wrapper (place it above the first fetcher, after `ensureOk`):
```typescript
/**
 * fetch wrapper for the maki API: attaches the bearer token when set, and on a 401 clears the
 * stored token and fires `maki:unauthorized` so the auth gate can re-prompt. All /api calls go
 * through this so auth is uniform.
 */
export async function apiFetch(input: string, init?: RequestInit): Promise<Response> {
  const token = getAuthToken();
  const headers = new Headers(init?.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const r = await fetch(input, { ...init, headers });
  if (r.status === 401) {
    clearAuthToken();
    window.dispatchEvent(new CustomEvent("maki:unauthorized"));
  }
  return r;
}
```

Then replace every `await fetch(` that targets an `/api/...` URL in this file with `await apiFetch(` (15 call sites — all of them point at `/api`). Leave the `Headers`/`ensureOk` logic intact; `apiFetch` accepts the same `(input, init)` shape, so calls passing a `{ method, headers, body }` init (rollback, run-task) work unchanged.

- [ ] **Step 5: Add `auth_required` to the config type + default**

In `frontend/src/api.ts`, add to `interface AppConfigResponse` (after `deploy_timeline_enabled`):
```typescript
  auth_required: boolean;
```

In `frontend/src/components/config-provider.tsx`, add to `DEFAULT_APP_CONFIG` (after `deploy_timeline_enabled: true,`):
```typescript
  auth_required: false,
```

- [ ] **Step 6: Run to verify tests pass + typecheck**

Run: `cd frontend && npm test -- --run auth-token api`
Expected: PASS.
Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/auth-token.ts frontend/src/lib/auth-token.test.ts frontend/src/api.ts frontend/src/api.test.ts frontend/src/components/config-provider.tsx
git commit -m "feat(security): frontend bearer-token store + apiFetch wrapper"
```

---

## Task 9: Frontend auth gate + boot wiring

**Files:**
- Create: `frontend/src/components/auth-gate.tsx`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/components/auth-gate.test.tsx` (create)

> The gate sits inside `ConfigProvider` (so it can read `auth_required` from `useConfig`) and wraps the app content. When auth is required and no token is stored, it renders the login form and does NOT render children — so no data query fires a doomed 401. On `maki:unauthorized` it drops back to the login form.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/auth-gate.test.tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { AuthGate } from "@/components/auth-gate";
import { clearAuthToken, setAuthToken } from "@/lib/auth-token";

// Drive the gate's view of config without standing up the real provider/network.
vi.mock("@/components/config-provider", async (orig) => {
  const actual = await orig<typeof import("@/components/config-provider")>();
  return { ...actual, useConfig: () => mockConfig };
});
let mockConfig: { auth_required: boolean } = { auth_required: false };

afterEach(() => {
  clearAuthToken();
  mockConfig = { auth_required: false };
});

test("renders children when auth is not required", () => {
  mockConfig = { auth_required: false };
  render(
    <AuthGate>
      <div>dashboard</div>
    </AuthGate>,
  );
  expect(screen.getByText("dashboard")).toBeInTheDocument();
});

test("renders the login form when auth required and no token", () => {
  mockConfig = { auth_required: true };
  render(
    <AuthGate>
      <div>dashboard</div>
    </AuthGate>,
  );
  expect(screen.queryByText("dashboard")).not.toBeInTheDocument();
  expect(screen.getByLabelText(/token/i)).toBeInTheDocument();
});

test("submitting a token reveals the dashboard", () => {
  mockConfig = { auth_required: true };
  render(
    <AuthGate>
      <div>dashboard</div>
    </AuthGate>,
  );
  fireEvent.change(screen.getByLabelText(/token/i), { target: { value: "sekret" } });
  fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
  expect(screen.getByText("dashboard")).toBeInTheDocument();
});

test("re-gates on maki:unauthorized", () => {
  mockConfig = { auth_required: true };
  setAuthToken("good");
  render(
    <AuthGate>
      <div>dashboard</div>
    </AuthGate>,
  );
  expect(screen.getByText("dashboard")).toBeInTheDocument();
  fireEvent(window, new CustomEvent("maki:unauthorized"));
  expect(screen.queryByText("dashboard")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npm test -- --run auth-gate`
Expected: FAIL — `@/components/auth-gate` not found.

- [ ] **Step 3: Implement the gate**

```tsx
// frontend/src/components/auth-gate.tsx
import { useEffect, useState, type ReactNode } from "react";

import { useConfig } from "@/components/config-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { getAuthToken, setAuthToken } from "@/lib/auth-token";

/**
 * Gates the app behind the optional bearer token. When the backend requires auth (config
 * `auth_required`) and no token is stored, shows a login form instead of the app — so no data
 * query fires an inevitable 401. Listens for `maki:unauthorized` (emitted by apiFetch on a 401) to
 * drop back to the form when a token goes stale.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const { auth_required } = useConfig();
  const [token, setToken] = useState<string | null>(() => getAuthToken());
  const [entry, setEntry] = useState("");

  useEffect(() => {
    const onUnauth = () => setToken(null);
    window.addEventListener("maki:unauthorized", onUnauth);
    return () => window.removeEventListener("maki:unauthorized", onUnauth);
  }, []);

  if (!auth_required || token) return <>{children}</>;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!entry) return;
    setAuthToken(entry);
    setToken(entry);
  };

  return (
    <div className="flex min-h-svh items-center justify-center p-6">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4">
        <div className="space-y-1.5">
          <h1 className="text-lg font-semibold">Sign in</h1>
          <p className="text-sm text-muted-foreground">
            This instance requires an access token. Paste the value of{" "}
            <code className="font-mono">MAKI_AUTH_TOKEN</code>.
          </p>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="auth-token">Access token</Label>
          <Input
            id="auth-token"
            type="password"
            value={entry}
            onChange={(e) => setEntry(e.target.value)}
            autoFocus
          />
        </div>
        <Button type="submit" className="w-full">
          Sign in
        </Button>
      </form>
    </div>
  );
}
```

> If `@/components/ui/label` doesn't exist, generate it: `cd frontend && npx shadcn@latest add label`. `button` and `input` already exist under `frontend/src/components/ui/`.

- [ ] **Step 4: Wire it into the app shell**

In `frontend/src/App.tsx`, wrap the app's rendered content in `<AuthGate>…</AuthGate>` (it must be inside `ConfigProvider` so `useConfig` works). Add the import:
```typescript
import { AuthGate } from "@/components/auth-gate";
```
Find where `ConfigProvider` wraps the routes/shell and place `<AuthGate>` as its direct child, wrapping everything below it. (Read `App.tsx` first to match the exact JSX; the provider boundary is in either `App.tsx` or `main.tsx` — `ConfigProvider` is consumed via `useConfig`, so the gate goes inside that provider.)

- [ ] **Step 5: Run to verify it passes + typecheck + full frontend suite**

Run: `cd frontend && npm test -- --run auth-gate`
Expected: PASS (4 tests).
Run: `cd frontend && npx tsc --noEmit && npm test -- --run`
Expected: no type errors; whole suite green.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/auth-gate.tsx frontend/src/components/auth-gate.test.tsx frontend/src/App.tsx
git commit -m "feat(security): SPA auth gate (login + 401 re-gate)"
```

---

## Task 10: Logging-hygiene invariants + guard tests

**Files:**
- Create: `backend/tests/test_logging_hygiene.py`
- Modify: `backend/src/maki/api.py` (comment only) and `backend/src/maki/auth.py` if a leak is found

> Today maki logs no bodies/secrets (verified). This task makes that an explicit, guarded invariant: (1) no body-logging middleware is registered, (2) the bearer token never appears in a log record.

- [ ] **Step 1: Write the tests**

```python
# backend/tests/test_logging_hygiene.py
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from maki.api import app
from maki.auth import BearerAuthMiddleware


def test_no_custom_body_logging_middleware():
    # The only BaseHTTPMiddleware maki adds is the (optional) auth gate. Any other custom
    # BaseHTTPMiddleware is a red flag for body/response logging — fail so it gets reviewed.
    custom = [
        m.cls.__name__
        for m in app.user_middleware
        if isinstance(m.cls, type)
        and issubclass(m.cls, BaseHTTPMiddleware)
        and m.cls is not BearerAuthMiddleware
    ]
    assert custom == [], f"unexpected BaseHTTPMiddleware (possible body logging): {custom}"


def test_auth_failure_does_not_log_the_token(caplog):
    sub = FastAPI()

    @sub.get("/api/secret")
    def secret():
        return {"ok": True}

    sub.add_middleware(BearerAuthMiddleware, token="super-secret-token")
    client = TestClient(sub, headers={"Authorization": "Bearer super-secret-token"})
    with caplog.at_level(logging.DEBUG):
        client.get("/api/secret")
    assert "super-secret-token" not in caplog.text
```

- [ ] **Step 2: Run to verify they pass**

Run: `cd backend && .venv/bin/pytest tests/test_logging_hygiene.py -v`
Expected: PASS. If `test_no_custom_body_logging_middleware` fails, an unexpected middleware exists — investigate before forcing the test green.

- [ ] **Step 3: Document the invariant**

In `backend/src/maki/api.py`, add a comment directly above the `app = FastAPI(...)` line:
```python
# Logging-hygiene invariant: maki never logs request/response bodies or secrets. The access log is
# method/path/status only; the bearer token, GITHUB_TOKEN, and env-var values must never reach a
# log. Guarded by tests/test_logging_hygiene.py — do not add body-logging middleware.
```

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_logging_hygiene.py backend/src/maki/api.py
git commit -m "test(security): guard logging hygiene (no body/secret logging)"
```

---

## Task 11: Docs — security section + run command

**Files:**
- Modify: `README.md`
- Modify: `backend/README.md`

> The maki app is not in `docker-compose.yml` (only Postgres is), so the publish guidance lives in the Dockerfile (done in Task 3) and the READMEs — not compose.

- [ ] **Step 1: Update the root README quickstart run command**

In `README.md`, replace the local-run line (currently `uvicorn maki.api:app --reload --port 8787 --app-dir src`) with the guarded launcher:
```bash
# Start the server (loopback-only by default; the bind guard refuses non-loopback without opt-in):
MAKI_RELOAD=1 python -m maki.server
# → http://localhost:8787/api/services
```

- [ ] **Step 2: Add a Security section to the root README**

Add a `## Security` section (after the Configuration section) with this content:
```markdown
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
```

- [ ] **Step 3: Update backend/README run instructions**

In `backend/README.md`, under `## Run`, replace the `uvicorn maki.api:app …` command with:
```bash
# Loopback-only by default; --reload via MAKI_RELOAD=1.
MAKI_RELOAD=1 python -m maki.server
```
And add a one-line pointer: `See the root README "Security" section for the auth token and bind options.`

- [ ] **Step 4: Verify the launcher command actually works**

Run (from `backend/`, venv active, config + Postgres up): `MAKI_RELOAD=1 timeout-free manual check` — start `python -m maki.server` in one shell, then in another:
```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8787/health
```
Expected: `200`. Stop the server (Ctrl-C). (If running headless, at minimum confirm `python -c "import maki.server"` imports cleanly.)

- [ ] **Step 5: Commit**

```bash
git add README.md backend/README.md
git commit -m "docs(security): security section + guarded launch command"
```

---

## Self-Review

**Spec coverage:**
- Layer 1 (bind guard) → Tasks 2, 3. ✓
- Layer 2 (Host allowlist) → Task 4. ✓
- Layer 3 (CORS closed) → Task 5. ✓
- Layer 4 (bearer token) → Tasks 1, 6, 7 (backend) + 8, 9 (frontend). ✓
- Logging hygiene → Task 10. ✓
- Config-lives-in-env split → Task 1 (fields aliased to `MAKI_*`, none in config.yaml). ✓
- Docs (Dockerfile/README, compose N/A) → Tasks 3, 11. ✓
- Env-values feature kept as-is → no task touches `service_env`. ✓ (correct — out of scope)
- Setup DX (doctor/bootstrap) → intentionally absent (deferred). ✓

**Type/name consistency:** `auth_token`/`auth_required`/`trusted_hosts` (Task 1) used in Tasks 4, 6, 7. `BearerAuthMiddleware`/`is_auth_exempt` (Task 6) used in Task 10. `apiFetch`/`getAuthToken`/`setAuthToken`/`clearAuthToken` (Task 8) used in Task 9. `auth_required` added to `UiConfigResponse` (Task 7), `AppConfigResponse` + `DEFAULT_APP_CONFIG` (Task 8), consumed by `AuthGate` (Task 9). `maki.main:app` import string consistent (Task 3). Consistent. ✓

**Placeholder scan:** every code step has complete code; commands have expected output. The only "read first" note is Task 9 Step 4 (App.tsx JSX placement) — unavoidable, since the exact provider boundary must be matched in-file; the instruction names exactly what to find and why.

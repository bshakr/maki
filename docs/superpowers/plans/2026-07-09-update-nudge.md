# Update Nudge + `make update` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tell devs when their clone is behind origin (terminal line on launch + sidebar badge) and give them one command — `make update` — to get current.

**Architecture:** A new `maki.version` backend module runs read-only git commands (`rev-parse`, `ls-remote`, `merge-base`, `rev-list`) via subprocess to decide whether the clone is behind its upstream. The same check backs three surfaces: a `python -m maki.version.nudge` one-liner run by `make dev`/`make backend`, a cached `GET /api/version` endpoint, and an `UpdateBadge` sidebar component polling it. `make update` is `git pull --ff-only` + the already-idempotent `make setup`.

**Tech Stack:** Python 3.11 / FastAPI / pytest (backend), React 19 + react-query / vitest (frontend), GNU make.

**Spec:** `docs/superpowers/specs/2026-07-09-update-nudge-design.md`

## Global Constraints

- **Never invent staleness:** every failure mode (not a git repo, detached HEAD, no upstream, offline, timeout) must yield `update_available: false` and total silence in the terminal.
- **Never block startup:** git subprocess calls carry a 3-second timeout; the nudge always exits 0.
- **No mutation:** the check must not fetch, pull, or write any git state. Only `make update` (explicit, user-run) pulls, and only fast-forward (`--ff-only`).
- Run backend commands from `backend/`, frontend commands from `frontend/` (repo convention).
- Comment style: sparse, *why*-only comments matching the existing codebase; no narrating comments.

---

### Task 1: Version check service (`maki.version.service`)

**Files:**
- Modify: `backend/src/maki/schemas.py` (append at end of file)
- Create: `backend/src/maki/version/__init__.py` (empty)
- Create: `backend/src/maki/version/service.py`
- Create: `backend/tests/version/__init__.py` (empty)
- Test: `backend/tests/version/test_service.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `maki.schemas.VersionResponse` (pydantic model: `current_sha: str | None`, `upstream: str | None`, `behind_by: int | None`, `update_available: bool`) and `maki.version.service.check_version() -> VersionResponse`. Tasks 2 and 3 import both.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/version/__init__.py` (empty file) and `backend/tests/version/test_service.py`:

```python
from subprocess import CompletedProcess, TimeoutExpired
from unittest.mock import patch

from maki.version.service import check_version

HEAD = ("rev-parse", "HEAD")
UPSTREAM = ("rev-parse", "--abbrev-ref", "@{upstream}")
LS_REMOTE = ("ls-remote", "origin", "refs/heads/main")
IS_ANCESTOR = ("merge-base", "--is-ancestor", "bbb", "HEAD")
COUNT = ("rev-list", "--count", "HEAD..bbb")

FAIL = (128, "")


def fake_git(responses):
    """subprocess.run stand-in keyed on the git arg tuple; unknown commands fail like git."""

    def run(cmd, **kwargs):
        rc, out = responses.get(tuple(cmd[1:]), FAIL)
        if rc is TimeoutExpired:
            raise TimeoutExpired(cmd, 3.0)
        return CompletedProcess(cmd, rc, stdout=out, stderr="")

    return run


def check_with(responses):
    with patch("maki.version.service.subprocess.run", side_effect=fake_git(responses)):
        return check_version()


def test_behind_reports_update_with_count():
    status = check_with(
        {
            HEAD: (0, "aaa\n"),
            UPSTREAM: (0, "origin/main\n"),
            LS_REMOTE: (0, "bbb\trefs/heads/main\n"),
            IS_ANCESTOR: (1, ""),
            COUNT: (0, "4\n"),
        }
    )
    assert status.update_available is True
    assert status.behind_by == 4
    assert status.current_sha == "aaa"
    assert status.upstream == "origin/main"


def test_up_to_date_when_remote_tip_matches_head():
    status = check_with(
        {
            HEAD: (0, "aaa\n"),
            UPSTREAM: (0, "origin/main\n"),
            LS_REMOTE: (0, "aaa\trefs/heads/main\n"),
        }
    )
    assert status.update_available is False
    assert status.current_sha == "aaa"


def test_local_ahead_is_not_behind():
    # Remote tip is an ancestor of HEAD → we have everything the remote has.
    status = check_with(
        {
            HEAD: (0, "aaa\n"),
            UPSTREAM: (0, "origin/main\n"),
            LS_REMOTE: (0, "bbb\trefs/heads/main\n"),
            IS_ANCESTOR: (0, ""),
        }
    )
    assert status.update_available is False


def test_unknown_remote_object_reports_update_without_count():
    # ls-remote doesn't fetch: a never-seen remote sha fails merge-base and rev-list.
    status = check_with(
        {
            HEAD: (0, "aaa\n"),
            UPSTREAM: (0, "origin/main\n"),
            LS_REMOTE: (0, "bbb\trefs/heads/main\n"),
            IS_ANCESTOR: FAIL,
            COUNT: FAIL,
        }
    )
    assert status.update_available is True
    assert status.behind_by is None


def test_offline_ls_remote_failure_is_silent():
    status = check_with(
        {
            HEAD: (0, "aaa\n"),
            UPSTREAM: (0, "origin/main\n"),
            LS_REMOTE: FAIL,
        }
    )
    assert status.update_available is False


def test_ls_remote_timeout_is_silent():
    status = check_with(
        {
            HEAD: (0, "aaa\n"),
            UPSTREAM: (0, "origin/main\n"),
            LS_REMOTE: (TimeoutExpired, ""),
        }
    )
    assert status.update_available is False


def test_not_a_git_repo_is_silent():
    status = check_with({})
    assert status.update_available is False
    assert status.current_sha is None


def test_no_upstream_is_silent():
    status = check_with({HEAD: (0, "aaa\n")})
    assert status.update_available is False
    assert status.current_sha == "aaa"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/pytest tests/version/test_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'maki.version'`

- [ ] **Step 3: Add the schema and implement the service**

Append to `backend/src/maki/schemas.py`:

```python
class VersionResponse(BaseModel):
    """Freshness of this clone vs its upstream branch tip.

    All-defaults means "couldn't check" (not a repo, no upstream, offline) — the UI hides
    the badge and the terminal nudge stays silent. ``behind_by`` is null when the remote
    tip object isn't known locally (ls-remote doesn't fetch), so a count can't be computed.
    """

    current_sha: str | None = None
    upstream: str | None = None  # e.g. "origin/main"
    behind_by: int | None = None
    update_available: bool = False
```

Create `backend/src/maki/version/__init__.py` (empty) and `backend/src/maki/version/service.py`:

```python
import subprocess

from maki.schemas import VersionResponse

GIT_TIMEOUT_SECONDS = 3.0


def _git(*args: str) -> str | None:
    """Run a git command; None on any failure (not a repo, offline, timeout, non-zero exit)."""
    try:
        out = subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=GIT_TIMEOUT_SECONDS
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip()


def check_version() -> VersionResponse:
    """Compare local HEAD with the upstream branch tip on the remote, without fetching.

    ls-remote is a single read-only network call; "behind" means the remote tip isn't an
    ancestor of HEAD. Every failure degrades to update_available=False — the nudge must
    never invent staleness.
    """
    head = _git("rev-parse", "HEAD")
    if head is None:
        return VersionResponse()
    upstream = _git("rev-parse", "--abbrev-ref", "@{upstream}")
    if upstream is None or "/" not in upstream:
        return VersionResponse(current_sha=head)
    remote, _, branch = upstream.partition("/")
    listed = _git("ls-remote", remote, f"refs/heads/{branch}")
    if not listed:
        return VersionResponse(current_sha=head, upstream=upstream)
    remote_sha = listed.split()[0]
    if remote_sha == head:
        return VersionResponse(current_sha=head, upstream=upstream)
    # Remote tip that's an ancestor of HEAD means we're ahead, not behind. A never-fetched
    # remote sha fails merge-base (and rev-list below) — then we know only that the remote
    # moved: report an update without a count.
    if _git("merge-base", "--is-ancestor", remote_sha, "HEAD") is not None:
        return VersionResponse(current_sha=head, upstream=upstream)
    count = _git("rev-list", "--count", f"HEAD..{remote_sha}")
    behind = int(count) if count and count.isdigit() else None
    return VersionResponse(
        current_sha=head, upstream=upstream, behind_by=behind, update_available=True
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/pytest tests/version/test_service.py -v`
Expected: 8 passed

- [ ] **Step 5: Lint and commit**

```bash
cd backend && .venv/bin/ruff check src tests && cd ..
git add backend/src/maki/schemas.py backend/src/maki/version/ backend/tests/version/
git commit -m "feat: version check service — is this clone behind its upstream?"
```

---

### Task 2: `GET /api/version` endpoint with hourly re-check

**Files:**
- Create: `backend/src/maki/version/routes.py`
- Modify: `backend/src/maki/api.py` (import + `include_router`, alphabetical with the others)
- Test: `backend/tests/version/test_routes.py`

**Interfaces:**
- Consumes: `maki.version.service.check_version() -> VersionResponse`, `maki.schemas.VersionResponse` (Task 1).
- Produces: `GET /api/version` returning the `VersionResponse` JSON shape `{current_sha, upstream, behind_by, update_available}`. Task 4's frontend fetcher relies on exactly these field names. Module attribute `maki.version.routes._cached` (test reset point).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/version/test_routes.py`:

```python
from unittest.mock import patch

from fastapi.testclient import TestClient

import maki.version.routes as version_routes
from maki.main import app
from maki.schemas import VersionResponse


def get_version(fake: VersionResponse):
    version_routes._cached = None
    with patch("maki.version.routes.check_version", return_value=fake) as check:
        client = TestClient(app)
        first = client.get("/api/version")
        second = client.get("/api/version")
    return first, second, check


def test_returns_check_result():
    fake = VersionResponse(
        current_sha="aaa", upstream="origin/main", behind_by=4, update_available=True
    )
    r, _, _ = get_version(fake)
    assert r.status_code == 200
    assert r.json() == {
        "current_sha": "aaa",
        "upstream": "origin/main",
        "behind_by": 4,
        "update_available": True,
    }


def test_result_is_cached_between_requests():
    _, second, check = get_version(VersionResponse())
    assert second.status_code == 200
    check.assert_called_once()


def test_stale_cache_rechecks():
    # Negative sentinel: monotonic() is always >= 0, so this entry is guaranteed stale.
    version_routes._cached = (-2 * version_routes.RECHECK_SECONDS, VersionResponse())
    fresh = VersionResponse(current_sha="ccc", update_available=True)
    with patch("maki.version.routes.check_version", return_value=fresh):
        client = TestClient(app)
        r = client.get("/api/version")
    assert r.json()["current_sha"] == "ccc"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/pytest tests/version/test_routes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'maki.version.routes'`

- [ ] **Step 3: Implement the route and register it**

Create `backend/src/maki/version/routes.py`:

```python
import time

from fastapi import APIRouter

from maki.schemas import VersionResponse
from maki.version.service import check_version

router = APIRouter(prefix="/api")

RECHECK_SECONDS = 3600.0

# (checked_at monotonic, result). Long-running dev sessions re-hit the remote hourly at most;
# the SPA can poll freely without generating network calls.
_cached: tuple[float, VersionResponse] | None = None


@router.get("/version", response_model=VersionResponse)
def get_version() -> VersionResponse:
    global _cached
    now = time.monotonic()
    if _cached is None or now - _cached[0] > RECHECK_SECONDS:
        _cached = (now, check_version())
    return _cached[1]
```

Modify `backend/src/maki/api.py` — add the import (keeping the block alphabetical):

```python
from maki.version.routes import router as version_router
```

and register it after the existing `app.include_router(logs_router)` line:

```python
app.include_router(version_router)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/pytest tests/version/ -v`
Expected: 11 passed (8 service + 3 routes)

- [ ] **Step 5: Lint and commit**

```bash
cd backend && .venv/bin/ruff check src tests && cd ..
git add backend/src/maki/version/routes.py backend/src/maki/api.py backend/tests/version/test_routes.py
git commit -m "feat: GET /api/version — clone freshness, re-checked hourly"
```

---

### Task 3: Terminal nudge + `make update`

**Files:**
- Create: `backend/src/maki/version/nudge.py`
- Modify: `Makefile` (new `update` + `_update-hint` targets; wire hint into `dev` and `backend`)
- Test: `backend/tests/version/test_nudge.py`

**Interfaces:**
- Consumes: `maki.version.service.check_version() -> VersionResponse` (Task 1).
- Produces: `python -m maki.version.nudge` (prints one line when behind, nothing otherwise, always exits 0); `make update` target. Nothing downstream consumes these.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/version/test_nudge.py`:

```python
from unittest.mock import patch

from maki.schemas import VersionResponse
from maki.version import nudge


def run_nudge(capsys, fake: VersionResponse) -> str:
    with patch("maki.version.nudge.check_version", return_value=fake):
        nudge.main()
    return capsys.readouterr().out


def test_silent_when_up_to_date(capsys):
    assert run_nudge(capsys, VersionResponse(current_sha="aaa")) == ""


def test_silent_when_check_could_not_run(capsys):
    assert run_nudge(capsys, VersionResponse()) == ""


def test_prints_count_and_upstream_when_behind(capsys):
    out = run_nudge(
        capsys,
        VersionResponse(
            current_sha="aaa", upstream="origin/main", behind_by=4, update_available=True
        ),
    )
    assert "4 commits behind origin/main" in out
    assert "make update" in out


def test_singular_commit(capsys):
    out = run_nudge(
        capsys,
        VersionResponse(
            current_sha="aaa", upstream="origin/main", behind_by=1, update_available=True
        ),
    )
    assert "1 commit behind origin/main" in out


def test_countless_update_still_nudges(capsys):
    out = run_nudge(
        capsys,
        VersionResponse(current_sha="aaa", upstream="origin/main", update_available=True),
    )
    assert "behind origin/main" in out
    assert "make update" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/pytest tests/version/test_nudge.py -v`
Expected: FAIL — `ImportError: cannot import name 'nudge'`

- [ ] **Step 3: Implement the nudge module**

Create `backend/src/maki/version/nudge.py`:

```python
"""Terminal nudge: one line when the clone is behind its upstream, silence otherwise.

Run by ``make dev`` / ``make backend`` before starting servers. Must never fail or block
the build — check failures are silent and the process always exits 0.
"""

from maki.version.service import check_version

# Match the Makefile's ✓/!/cyan markers so the line reads like the rest of the tooling.
WARN = "\033[33m!\033[0m"
CYAN = "\033[36m"
RESET = "\033[0m"


def main() -> None:
    status = check_version()
    if not status.update_available:
        return
    where = status.upstream or "origin"
    if status.behind_by:
        plural = "" if status.behind_by == 1 else "s"
        behind = f"{status.behind_by} commit{plural} behind {where}"
    else:
        behind = f"behind {where}"
    print(f"{WARN} maki: {behind} — run {CYAN}make update{RESET} to get the latest")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/pytest tests/version/test_nudge.py -v`
Expected: 5 passed

- [ ] **Step 5: Wire the Makefile**

Four edits to `Makefile`:

1. Add `update` to the `.PHONY` line (line 37-38), which becomes:

```make
.PHONY: help setup dev doctor venv backend-deps frontend-deps config db-up migrate \
        backend frontend test check clean update
```

2. Add the `update` target after `migrate` (end of the Bootstrap section, ~line 107). `--ff-only` makes a dirty tree / local commits a clean git error instead of a surprise merge; setup is already idempotent:

```make
update: ## Pull the latest and re-run setup (safe: fast-forward only)
	@git pull --ff-only
	@$(MAKE) --no-print-directory setup
```

3. Add `_update-hint` next to `_aws-hint` (after line 133). Guarded so a missing venv (fresh clone, pre-setup) skips silently:

```make
# Advisory only: one line when the clone is behind origin. Silent offline; never fails.
.PHONY: _update-hint
_update-hint:
	@[ -x "$(PY)" ] && $(PY) -m maki.version.nudge || true
```

4. Call it from `dev` and `backend` — add this line directly under the existing `@$(MAKE) --no-print-directory _aws-hint` line in **both** targets:

```make
	@$(MAKE) --no-print-directory _update-hint
```

- [ ] **Step 6: Verify the Makefile by hand**

Run: `make _update-hint`
Expected: exits 0. Prints nothing (clone up to date / offline) or a single yellow-`!` nudge line — either is correct; it must not error.

Run: `make -n update`
Expected: prints `git pull --ff-only` followed by the setup recipe — confirms wiring without executing.

- [ ] **Step 7: Lint and commit**

```bash
cd backend && .venv/bin/ruff check src tests && cd ..
git add backend/src/maki/version/nudge.py backend/tests/version/test_nudge.py Makefile
git commit -m "feat: launch nudge + make update"
```

---

### Task 4: Frontend — `fetchVersion` + sidebar `UpdateBadge`

**Files:**
- Modify: `frontend/src/api.ts` (append at end)
- Create: `frontend/src/components/update-badge.tsx`
- Modify: `frontend/src/components/app-sidebar.tsx` (render `<UpdateBadge />` in the footer)
- Test: `frontend/src/components/update-badge.test.tsx`

**Interfaces:**
- Consumes: `GET /api/version` → `{current_sha, upstream, behind_by, update_available}` (Task 2); existing `apiFetch`/`ensureOk` helpers in `frontend/src/api.ts`.
- Produces: `fetchVersion(): Promise<VersionResponse>` and `UpdateBadge` (renders `null` unless an update is available). Nothing downstream consumes these.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/update-badge.test.tsx` (global-fetch mock + `SidebarProvider` wrapper, same pattern as `nav-user.test.tsx`):

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { UpdateBadge } from "@/components/update-badge";
import { SidebarProvider } from "@/components/ui/sidebar";

afterEach(() => vi.restoreAllMocks());

function mockVersion(body: unknown) {
  vi.spyOn(global, "fetch").mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => body,
  } as Response);
}

function renderBadge() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SidebarProvider>
        <UpdateBadge />
      </SidebarProvider>
    </QueryClientProvider>,
  );
}

test("shows the badge with a behind count when an update is available", async () => {
  mockVersion({
    current_sha: "aaa",
    upstream: "origin/main",
    behind_by: 4,
    update_available: true,
  });
  renderBadge();
  await waitFor(() =>
    expect(screen.getByText(/update available/i)).toBeInTheDocument(),
  );
  expect(screen.getByText(/4 commits behind/i)).toBeInTheDocument();
});

test("renders nothing when up to date", async () => {
  mockVersion({
    current_sha: "aaa",
    upstream: "origin/main",
    behind_by: null,
    update_available: false,
  });
  renderBadge();
  // Let the query settle, then assert the badge never appeared.
  await waitFor(() => expect(global.fetch).toHaveBeenCalled());
  expect(screen.queryByText(/update available/i)).not.toBeInTheDocument();
});

test("renders nothing while the check errors", async () => {
  vi.spyOn(global, "fetch").mockRejectedValue(new Error("network down"));
  renderBadge();
  await waitFor(() => expect(global.fetch).toHaveBeenCalled());
  expect(screen.queryByText(/update available/i)).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npm run test -- src/components/update-badge.test.tsx`
Expected: FAIL — cannot resolve `@/components/update-badge`

- [ ] **Step 3: Add the fetcher and the component**

Append to `frontend/src/api.ts`:

```ts
export interface VersionResponse {
  current_sha: string | null;
  /** Upstream ref compared against, e.g. "origin/main". Null when the check couldn't run. */
  upstream: string | null;
  /** Commits behind the upstream tip; null when unknown (remote object never fetched). */
  behind_by: number | null;
  update_available: boolean;
}

// Clone freshness (is this checkout behind its upstream?). The backend caches the git
// check and re-runs it hourly, so polling this is cheap.
export async function fetchVersion(): Promise<VersionResponse> {
  const r = await apiFetch("/api/version");
  return (await ensureOk(r, "load version")).json();
}
```

Create `frontend/src/components/update-badge.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query"
import { CircleArrowUp } from "lucide-react"

import { fetchVersion } from "@/api"
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar"

// Quiet "your clone is behind" affordance for long-running dev sessions: `make dev` can stay
// up for days, so a launch-time terminal nudge alone goes stale. Hidden entirely when up to
// date or when the check couldn't run (offline, not a repo) — absence of signal is silence.
export function UpdateBadge() {
  const { data } = useQuery({
    queryKey: ["version"],
    queryFn: fetchVersion,
    // Backend re-checks the remote hourly at most; poll well under that without hammering.
    refetchInterval: 15 * 60_000,
    retry: false,
  })

  if (!data?.update_available) return null

  const detail = data.behind_by
    ? `${data.behind_by} commit${data.behind_by === 1 ? "" : "s"} behind`
    : "new version available"

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <SidebarMenuButton
          tooltip="Run `make update` to get the latest"
          className="text-amber-600 dark:text-amber-500"
        >
          <CircleArrowUp />
          <div className="grid flex-1 text-left leading-tight group-data-[collapsible=icon]:hidden">
            <span className="truncate text-sm font-medium">Update available</span>
            <span className="truncate text-xs text-muted-foreground">
              {detail} — make update
            </span>
          </div>
        </SidebarMenuButton>
      </SidebarMenuItem>
    </SidebarMenu>
  )
}
```

Modify `frontend/src/components/app-sidebar.tsx` — import it:

```tsx
import { UpdateBadge } from "@/components/update-badge"
```

and render it in the footer, above `NavUser`:

```tsx
      <SidebarFooter>
        <UpdateBadge />
        <NavUser />
      </SidebarFooter>
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npm run test -- src/components/update-badge.test.tsx`
Expected: 3 passed

- [ ] **Step 5: Lint, typecheck, commit**

```bash
cd frontend && npm run lint && npm run typecheck && cd ..
git add frontend/src/api.ts frontend/src/components/update-badge.tsx frontend/src/components/app-sidebar.tsx frontend/src/components/update-badge.test.tsx
git commit -m "feat: sidebar update-available badge polling /api/version"
```

---

### Task 5: Full gate + docs touch-up

**Files:**
- Modify: `README.md` (mention `make update` wherever targets are listed)
- Modify: `AGENTS.md` (add `update` to the Makefile line in the repo-layout block)

**Interfaces:**
- Consumes: everything above.
- Produces: green `make check`; docs current.

- [ ] **Step 1: Run the full gate**

Run: `make check`
Expected: ruff + eslint + tsc + pytest + vitest all pass. Fix anything red before proceeding.

- [ ] **Step 2: Update docs**

In `README.md`, find where make targets are described (grep for `make dev`) and add one line for `make update` — "pull the latest and re-run setup", matching the surrounding tone. In `AGENTS.md`, the repo-layout block line

```
  Makefile             # bootstrap + dev orchestration: make setup / dev / doctor / check
```

becomes

```
  Makefile             # bootstrap + dev orchestration: make setup / dev / doctor / check / update
```

- [ ] **Step 3: Commit**

```bash
git add README.md AGENTS.md
git commit -m "docs: document make update"
```

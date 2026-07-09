# Update nudge + one-command update

maki is a clone-and-run tool: devs `git clone`, `make setup`, `make dev`. There is no update
mechanism, so clones silently drift behind `origin/main` — both the code and the environment
(venv deps, npm deps, DB migrations). This design adds a low-friction way to notice you're
behind and a single command to get current.

Decisions made during brainstorming: **nudge, don't force** (no auto-pull, no blocking on
staleness), and surface the nudge **in the terminal and the web UI** (devs leave `make dev`
running for days, so a launch-only check goes stale itself).

## 1. Version detection — `git ls-remote` against `origin`

The check compares local `HEAD` with `git ls-remote origin <current-branch>` — a single
lightweight network call that doesn't touch the working tree (no fetch, no mutation of local
refs). "Behind" means the remote tip commit is not an ancestor of local `HEAD`; the
behind-by count comes from `git rev-list --count HEAD..<remote-sha>` after the remote sha is
known locally, and degrades to "update available" without a count when it isn't.

Why git and not the GitHub API: the repo is public so `ls-remote` needs no token, it respects
forks automatically (each clone compares against *its own* origin), and it avoids coupling
the check to `GITHUB_TOKEN` / repo-slug config when git already knows the answer.

## 2. Terminal nudge on launch

`make dev` and `make backend` run the check first — non-blocking, ~3 second timeout — and
print one friendly line in the existing `make doctor` style:

```
maki: 4 commits behind origin/main — run `make update` to get the latest
```

Silent when up to date, offline, or the check can't run. Startup is never blocked.

## 3. Backend endpoint + UI badge for long-running sessions

The backend runs the same check on startup and re-checks hourly (cached in between), exposed
as:

```
GET /api/version → { current_sha, behind_by, update_available }
```

`update_available` is `false` (and `behind_by` null) whenever the check can't run. The
frontend polls the endpoint with react-query and shows a small "Update available" badge in
the sidebar footer with a tooltip pointing at `make update`. Unobtrusive — no modal, no
toast.

## 4. `make update` — the upgrade path

One new Makefile target:

```
update: git pull --ff-only && make setup
```

`make setup` is already idempotent (venv, backend/frontend deps, migrations, config only if
absent), so updating is just pull + re-setup. `--ff-only` means a dirty tree or local
commits produce a clean git error instead of a surprise merge — the right failure mode for a
tool people may hack on locally.

## 5. Edge cases

- **No network / origin unreachable** — check skips silently: terminal prints nothing,
  endpoint reports `update_available: false`, badge hidden.
- **Non-main branch** — compare against that branch's upstream; no upstream or detached
  HEAD → skip.
- **Not a git repo** (tarball download) — skip.

## 6. Testing

- Backend: unit tests for the check logic with git invocations faked — behind, up to date,
  offline, not a repo, no upstream.
- Frontend: one vitest case asserting the badge renders/hides based on the `/api/version`
  response.
- The Makefile pieces stay thin enough to not need tests.

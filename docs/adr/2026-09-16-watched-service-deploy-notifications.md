# Watched-service deploy notifications

**Status:** Accepted — implemented on `watch-release` (migration `f7a83055ed2a`); PR not yet opened.

## Context

After merging, knowing that a service is actually live in prod — or that its release broke — meant
watching the maki dashboard. Notifying on every service in the fleet would be noise, so
notifications had to be opt-in per service, and had to work while maki is running headless.

## Decisions

1. **Notifications fire from the backend via a local subprocess**, not the browser. The ingest
   process is already long-lived on the operator's Mac; a Web Notifications approach only works
   with a maki tab open. `MacNotifier` prefers `terminal-notifier` when installed (argv-based, and
   its `-open` flag makes notifications clickable) and falls back to `osascript` with explicit
   escaping. This is the only subprocess in the codebase.
2. **Both failure sources are detected**: an ECS rollout ending `failed`/rolled back, and a failed
   GitHub Actions deploy job. A CI failure never reaches ECS, so ECS-only detection would be silent
   in exactly the case that matters most.
3. **A separate watcher loop** (`watch_interval_seconds`, default 45s) scoped to watched services
   only, running alongside the existing 5-minute fleet ingest rather than speeding it up.
4. **The watched set lives in Postgres behind one API** (`/api/watches`), driven by a CLI (primary)
   and a bell toggle in the SPA (secondary) — not a `maki.config.yaml` block, because the set
   changes often and from the terminal.
5. **Delivery is at-most-once by construction.** `sent_notifications` has a unique constraint on
   `(service, kind, key)`, and the watcher claims a row and commits *before* notifying: a crash can
   drop a notification but never duplicate one. Detecting whether the claim won requires
   `RETURNING` — `rowcount` is unreliable for an ORM-targeted `pg_insert` on SQLAlchemy 2.x +
   psycopg 3, and using it would have silently suppressed every notification the feature produced.
6. **The cold-start floor is a *completion*-time comparison against `service_watches.created_at`**:
   an event that finished before the watch existed is ignored, so opting in never replays history,
   but one already in flight when the watch is created still notifies — that is the operator's own
   merge-then-watch case. The API-level window is the lookback, not the watch: both ECS and GitHub
   filter on *creation* time, so flooring that at the watch would permanently hide the very deploy
   being waited on.
7. **CI deploy-job matching is service-token-based, not name-equality.** Real `Noryai/nory` job
   names are `deploy-<token> / deploy`, where the service lives in the caller segment and the token
   drops the ECS name's env/domain prefix (job token `timecard-sync` vs service
   `prod-workforce-payroll-timecard-sync`). Matching accepts `service == token` or
   `service.endswith("-" + token)`, with the separator boundary required. Against live job names,
   exact equality matched 0 of 7; this rule matches 6 of 7 while still excluding sibling services in
   the same monorepo (`inventory` is not blamed for `deploy-inventory-report-preload`). The 7th,
   `deploy-entity-sync-batch` → `prod-workforce-payroll-employee-sync-batch`, is a genuine naming
   divergence no derivation rule can bridge; it is pinned by a test as a documented limitation, and
   unmatched jobs on a failed run are logged at debug.
8. **ECS and CI checks are independently isolated.** The only raising call on the per-service path
   is `describe_services`, so a single shared `try` meant expired AWS credentials silently stopped
   *all* CI notifications. Each check now owns its `try`/rollback/warning.
9. **No author filter and no stuck-rollout timeout in v1.** A colleague's deploy breaking a watched
   service is worth hearing about; an `in_progress` rollout that never resolves stays silent.

## Alternatives rejected

- **Frontend Web Notifications** — requires an open tab, which defeats the purpose.
- **A `notifications:` block in `maki.config.yaml`** — needs a file edit plus a restart to change.
- **Reusing or speeding up the 5-minute ingest loop** — 5x the full-fleet ECS describes and GitHub
  enrichment for a benefit wanted on one service.
- **Merging the watcher into `maki/watches/`** — kept separate as `maki/notifications/`, following
  the existing `maki/ingest/` precedent for background machinery, and because `notifications`
  shares no prefix with `watches`.

## Consequences

- First subprocess in the codebase. AGENTS.md now records it as desktop UI, not deploy execution;
  the reads-live / writes-fake invariant is unchanged.
- First `useMutation` in the frontend.
- `GitHubActions` grew uncached read methods: its existing cache never expires, which is right for
  the deploy timeline and wrong for a poll loop.
- The CI scan currently runs per watched service rather than per repo, and is uncached, so GitHub
  API budget scales with the number of watches.

## Rollout

Stack order: additive migration `f7a83055ed2a` at the bottom (DDL applies in prod before the code
that uses it) → watches API → watcher loop → CLI → UI toggle.

New settings: `watch_enabled`, `watch_interval_seconds` (45), `watch_lookback_minutes` (120),
`notify_enabled` / `MAKI_NOTIFY_ENABLED`, `maki_base_url` / `MAKI_BASE_URL`.

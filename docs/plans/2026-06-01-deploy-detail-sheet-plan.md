# Deploy detail sheet (past deploy → side sheet)

**Goal:** clicking a past deploy in the history list opens a right-side Sheet showing that deploy's
detail: commit/PR header, an excerpt of the PR description, and the deploy timeline **for that
specific deploy** (not the current one).

**Reuse:** the existing `DeployTimeline` component + `/deploy-timeline` endpoint, extended to target a
specific `sha`/`revision`. The header data is already on the `DeployRecord` the history list holds —
the sheet only needs two new things: the PR body excerpt and a sha-scoped timeline.

---

## Pinned contracts

1. **Timeline for a specific deploy** — extend the existing endpoint with optional params:
   `GET /api/services/{name}/deploy-timeline?sha=<sha>&revision=<rev>` → same `DeployTimeline` schema.
   - No params → current deploy (existing behavior, unchanged).
   - `sha` given → CI segments from `jobs_for_sha(repo, sha)`; `revision` given → ECS segments from
     `deployment_for_revision(name, revision, family)`. `merged_at`/`sha` reflect the target deploy
     (when targeting a past deploy, `merged_at` can be omitted/null — committed_at isn't on the
     timeline input; keep `merged_at=null` if unknown, totals degrade gracefully).
   - Cache key must include sha+revision so different deploys don't collide.

2. **PR description** — `GET /api/services/{name}/pull?number=<n>` → `PullDescription`:
   ```json
   { "number": 4242, "title": "feat(wfm): …", "body_excerpt": "first ~600 chars…", "url": "https://github.com/acme/platform/pull/4242" }
   ```
   - Backend resolves repo via `repo_for(name)`, calls `GET /repos/{repo}/pulls/{n}` (GitHub),
     returns `title` + `body_excerpt` (first ~600 chars / first few lines of `body`, plain text —
     do not render markdown server-side). Defensive: no token / 404 / error → `title=null,
     body_excerpt=null` (never raise). Cache by (repo, number).

---

## Backend tasks
- `GitHubEnricher` (or `github_actions`/a small client): add `pull(repo, number) -> {title, body} | None`
  via `GET /repos/{repo}/pulls/{n}`, token-optional, cached, defensive (→ None on any failure).
- `TimelineService.get_timeline(service_name, sha=None, revision=None)` — thread optional target;
  when provided, use them for CI/ECS instead of resolving the current primary. Route accepts
  `sha`/`revision` query params. Cache key includes them.
- New `pull` route: `backend/src/maki/timeline/routes.py` or a small `pulls` module —
  `GET /api/services/{name}/pull?number=` → `PullDescription` (schema in `schemas.py`). Build the
  PR `url` as `https://github.com/{repo}/pull/{n}`. `body_excerpt` = first 600 chars of body, trimmed
  at a word boundary, with trailing "…" if truncated.
- Tests (mocked): timeline with sha+revision targets those (not current); pull endpoint returns
  title+excerpt, truncates long bodies, degrades to nulls without token / on 404.

## Frontend tasks
- `api.ts`: `fetchDeployTimeline(name, opts?: { sha?: string; revision?: number })` (adds query
  params); `interface PullDescription` + `fetchPullDescription(name, number)`.
- `DeployTimeline` component: optional `sha?: string` / `revision?: number` props → include in the
  query key + passed to `fetchDeployTimeline`. The current-deploy card keeps calling it with no
  sha/revision (current). No visual change.
- New `frontend/src/components/deploy-detail-sheet.tsx`: shadcn `Sheet` (side="right", wide e.g.
  `sm:max-w-xl`). Props `{ open, onOpenChange, service, deploy: DeployRecord | null }`. Renders:
  - Header: `AuthorAvatar` + commit message (title), then `sha↗ · PR #N↗ · author · {ago(registered_at)}`
    and the lead time (`finished_at` based) if present + the "not live" tag.
  - **PR description**: fetch `fetchPullDescription(service, prNumber)` (derive N from `deploy.pr_url`);
    show `title` (if any) + `body_excerpt` in a muted, `whitespace-pre-wrap` block; a "View PR" link.
    Loading + "No PR description" states. Skip the whole block if no `pr_url`.
  - **Timeline**: `<DeployTimeline service={service} sha={deploy.sha ?? undefined} revision={deploy.revision ?? undefined} />`.
  - A "Roll back" action in the sheet footer is NICE-TO-HAVE — skip for v1 (rollback stays on the row).
- Wire the trigger: in `ServiceDetailPage.tsx` `DeployHistoryItem`, make the card body clickable
  (role="button"/link + keyboard) to open the sheet with that `DeployRecord`; the existing "Roll back"
  button must `stopPropagation` so it doesn't open the sheet. Hoist sheet open-state + selected
  deploy into `ServiceDetailPage` (like the rollback dialog), render one `<DeployDetailSheet>`.
- Tests: clicking a history card opens the sheet (shows the commit message + a "View PR" link);
  rollback button does NOT open the sheet; PR excerpt renders from a mocked `fetchPullDescription`;
  the embedded timeline requests with the row's sha. Keep existing tests green.

## Notes
- All new GitHub/ECS calls read-only + failure-isolated.
- Per-deploy timeline reuses the 90-day ECS window caveat; CI (jobs_for_sha) works for any sha GitHub
  still has Actions history for.
- Don't fan out across the fleet — these fetch only when a sheet opens.

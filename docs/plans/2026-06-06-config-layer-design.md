# Config Layer — Design Spec (Project A)

**Date:** 2026-06-06
**Status:** Design approved, ready for implementation plan.

## Why this exists

maki was built reading **live Nory production** AWS + GitHub, with Nory-specific values
scattered across backend `settings.py`, frontend `lib/domains.ts`, URL builders, theme, and the
sidebar. Before maki can be considered for an open-source release, every Nory-specific value must
leave the code and live in one ingested config file, so the core runs neutral and a stranger
configures it without touching code.

This is **one of three independently-deliverable projects**, each valuable even if no OSS release
happens:

- **Project A — Config layer (this doc).** Extract all company-specific data into one config file;
  make the core run zero-config except for what only the operator can know.
- **Project B — Security posture review.** Understand and harden the live-AWS read surface
  (notably: `service_env` returns *plaintext env values*, not just names; no auth; binds
  `0.0.0.0`). Standalone.
- **Project C — Rename.** Drop the placeholder name "maki"; check PyPI/npm/name collisions.

A and B are independent and can run in parallel. C is trivial. After A + B + C, a fresh
**OSS-readiness re-review** decides on release.

This spec covers **Project A only**.

## Goal

One config file carries every company-specific value. Core ships neutral defaults and runs with
**zero config except Tier 1** (the two facts only the operator can know: AWS region + cluster).
Everything else is optional polish — delete any block and maki still runs.

## The config file

`maki.config.jsonc`, read by the backend at startup, validated with plain-English errors (never a
traceback). Two tiers:

```jsonc
{
  // ── TIER 1 — REQUIRED (only the operator can know these) ──
  "aws": {
    "region": "eu-west-1",
    "ecsCluster": "production"
  },

  // ── TIER 2 — ALL OPTIONAL (delete any block; maki still runs) ──

  // Which GitHub repo each ECS service deploys from. Grouped by repo (reads well for a
  // multi-service cluster; states each repo once). A service not listed here → deploy
  // enrichment (commit/PR/CI timeline) is simply skipped for it (fail-soft).
  "github": {
    "repos": [
      { "repo": "acme/platform", "services": ["inventory", "billing"] },
      { "repo": "acme/web",      "services": ["web-app"] }
    ]
  },

  // The Amplify web app, if any. OFF by default — a bare-ECS operator needs no Amplify and
  // gets no broken web-app row.
  "amplify": {
    "enabled": false,
    "appId": "...",
    "branch": "master",
    "serviceName": "web-app"
  },

  // Cosmetic. No logo — core ships a text wordmark only.
  "branding": {
    "appName": "Deploy Dashboard",
    "primaryColor": "#5F3BED"
  },

  // Group services on the board (was the hardcoded lib/domains.ts taxonomy).
  "grouping": {
    "rules": [ { "match": "wfm-", "label": "Workforce" } ]
  },

  // The merge → CI → rollout → live Gantt. Works with zero config (every job becomes a
  // segment, identical names grouped). Optional tuning is sub-sectioned BY SOURCE because the
  // timeline merges GitHub Actions + ECS data.
  "deployTimeline": {
    "enabled": true,
    "github": {                          // CI segments — from GitHub Actions jobs
      "groupMatrixJobs": true,           // merge "test (0)", "test (1)" into one "test" bar
      "hideJobsStartingWith": ["deploy-"],
      "hideJobsEndingWith": ["deploy"]   // per-service rollout jobs; measured from ECS instead
    }
    // "aws": { ... }                     // rollout segment — from ECS. No knobs today;
    //                                    // section reserved for when there are. (YAGNI)
  },

  // Sidebar external links (was hardcoded GitHub + AWS-console links).
  "links": [ { "label": "Runbook", "url": "https://..." } ],

  // Footer identity (drops the hardcoded bailey / user@example.com).
  "user": { "name": "user", "email": null }
}
```

## Two-tier contract

- **Tier 1 (required):** `aws.region`, `aws.ecsCluster`. No sensible default is possible — these
  point maki at real infrastructure. Missing → boot fails with a clear message.
- **Tier 2 (all optional):** every other block. Omit it and the corresponding feature uses a
  neutral default or is hidden. A stranger fills only Tier 1, deletes the rest, and gets a working
  neutral dashboard. Nory's private overlay fills Tier 2 with its theme, grouping, Amplify on,
  timeline tidy, links, repos.

This contract is the friendliness guarantee: **the minimum viable config is two lines.**

## Loading model — single source of truth

```
maki.config.jsonc
   │  read once at backend startup
   ▼
validate (friendly errors) ──▶ fail fast on bad/missing Tier 1
   │
   ├─ backend uses Tier 1 for boto3 (region, cluster)
   │
   └─ GET /api/config  serves the UI-relevant subset
        (branding, grouping rules, links, user, amplify.enabled, deployTimeline flags)
        │
        ▼
      SPA fetches on boot → no per-tenant rebuild, one image serves any tenant,
      no branding or secrets baked into the JS bundle
```

The backend owns the file. The frontend never reads it directly — it fetches the UI subset from
`/api/config`. This replaces the old plan's three competing frontend options
(`config.ts` / runtime / vite-define) with **runtime `/api/config` only** — simplest for a
stranger, one image for everyone.

Note (feeds Project B): `/api/config` exposes region / cluster / console-URL data to any client.
Not secret, but it widens the unauthenticated surface — Project B owns the auth/exposure posture.

## Resolution rules

### Service → repo (`github.repos`)
- Build a reverse index `service → repo` on load.
- Validate the **one-repo-per-service** invariant: a service listed under two repos → boot error
  (`"inventory" is listed under two repos`).
- Lookup: `index[service]` if present, else **no repo → enrichment skipped** (existing fail-soft
  behaviour; deploys still show from AWS, just without commit/PR/timeline).
- No template tokens, no strip rules, no default repo. Explicit and greppable beats clever and
  surprising. (If a future user with a huge monorepo objects to repetition, add an *optional*
  fallback then — not now.)

### Service → group (`grouping.rules`)
- Replaces the hardcoded `DOMAIN_RULES` in `frontend/src/lib/domains.ts`.
- The matching **function** (`serviceDomain()`) stays in core as generic logic; only the **rules
  data** moves to config. Rules come down via `/api/config`.

### Deploy timeline (`deployTimeline`)
- **Zero-config default:** fetch GitHub Actions jobs for the sha → each job becomes a segment,
  labelled by its raw job name, identical names grouped. Correct, possibly noisy. No "rollout"
  concept needed to render something useful.
- **Optional tuning** under `deployTimeline.github`: `groupMatrixJobs`, `hideJobsStartingWith`,
  `hideJobsEndingWith` — all plain verbs describing what happens to the picture.
- **Internal heuristics stay hidden** (not user knobs): the 30-min `_RUN_CLUSTER_GAP_SECONDS`
  run-clustering, and the reusable-workflow `" / "` `caller / suffix` name parsing. Sensible
  defaults in code; not exposed.
- The CI phase-grouping logic in `timeline/service.py` is already provider-agnostic (operates on
  normalized job dicts). Only `github_actions.py` is GitHub-specific. We name the config slot
  `github` (honest about today), **not** `ci`. A second CI provider is its own future project
  (extract a `CiProvider` interface, then rename the slot) — not built now (YAGNI), and naming it
  `ci` would falsely advertise multi-provider support.

## Code changes

### Backend
- `settings.py`: drop all Nory literal defaults (`aws_region`, `ecs_cluster`, `amplify_app_id`,
  `amplify_branch`, `default_github_repo`, `github_repo_overrides`, `timeline_rollout_job_suffixes`).
  Load + validate `maki.config.jsonc`. Keep generic operational defaults (`database_url`, SWR /
  ingest tunables).
- **Amplify optional** (addresses the fact Amplify isn't fully working and shouldn't be required):
  `inventory/service.py` skips the web-app row entirely when `amplify.enabled` is false. No
  Amplify config, no web-app row, no error.
- `aws/amplify_registry.py`: the hardcoded service name `"web-app"` (line ~21) comes from
  `amplify.serviceName`.
- GitHub repo resolution: replace `repo_for()` default+overrides with the `github.repos`
  reverse-index; unmapped service → skip.
- Timeline: implement the zero-config default + the `deployTimeline.github` knobs; keep the gap /
  separator heuristics internal.
- New `GET /api/config` route returning the UI subset.
- Neutralize the title string ("maki — Nory Deploy Console") via `branding.appName`.

### Frontend
- Delete the `DOMAIN_RULES` constant from `lib/domains.ts`; keep `serviceDomain()`, feed it rules
  from `/api/config`.
- Rewire to config (via `/api/config`): sidebar GitHub + AWS-console links (`app-sidebar.tsx`),
  the AWS-console / CloudWatch log-group URL builders (`current-deploy-section.tsx` —
  `${name}-production` log-group convention becomes a configurable template), `nav-user.tsx` user
  + env label, document title (`index.html`), theme `--primary` (from `branding.primaryColor`),
  the `maki-ui-theme` storage key → neutral.
- **Strip the logo** entirely (`logo.tsx` → text wordmark only; drop the Nory SVG).
- Default theme in `index.css` becomes a neutral palette (e.g. shadcn zinc/slate); the Nory violet
  arrives only via `branding.primaryColor`.

### Scaffolding
- Ship `config.example.jsonc` with a one-line plain-English comment on every field + a doc link.
- Neutral default theme + wordmark baked into core.

## First-run UX

- Missing/invalid Tier 1 → fatal boot error naming the field + pointing at `config.example.jsonc`
  (e.g. `maki.config.jsonc: "aws.region" is required — see config.example.jsonc`). Never a stack
  trace.
- Optional blocks: absent → neutral default or feature hidden. Bad shape (e.g.
  `hideJobsEndingWith` not a list) → clear validation message.

## Boundaries / design principle

- **Functions stay in core, data moves to config.** Generic *logic* (`serviceDomain()`,
  job→stage-label normalization, phase grouping, repo reverse-index) stays in the codebase. Only
  the *values* (rules, repos, knobs, theme, links, user) move to the config file.
- Each block is independently optional and independently understandable. A reader can answer
  "what is this block for and what happens if I delete it?" from the example file alone.

## Out of scope (other projects)

- Security hardening / auth / exposure posture — **Project B**. (This spec only notes where
  `/api/config` widens the surface.)
- Rename off "maki", name-collision checks — **Project C**.
- A pluggable multi-CI-provider abstraction — future, only if a real second provider appears.
- A `repoFor` template / strip-rules fallback for huge monorepos — only if a real user asks.

## Risks

- **Untested against any non-Nory account.** Genericizing keeps the *mocked* test suite green, but
  the parameterized build has never run against a second real ECS account. v0.1.0 portability is
  unverified; a demo/fixture mode (separate effort) would de-risk both this and public screenshots.
- The deploy timeline is the most environment-shaped feature; the zero-config default makes it
  *render* anywhere, but quality of grouping for non-reusable-workflow CI layouts is unverified.

# Config Layer — Implementation Plan (Project A)

> **For agentic workers:** each task below is dispatched to a **fresh subagent** that runs its own
> plan → TDD implement → review → fix → commit cycle (ship-ticket style). Tasks are **sequential**
> (hard dependency chain), all on one local branch `oss/config-layer`. No stacked branches, no PRs,
> no push — local only (see `CLAUDE.md`). Steps use checkbox (`- [ ]`) syntax for tracking.
> Each subagent's ship-ticket "review" phase uses the **`/code-review`** skill (diff-focused; no PRs
> here, so the PR-oriented reviewers are skipped).

**Goal:** Move every Nory-specific value out of the code into one ingested `maki.config.yaml`, so
the core runs neutral and zero-config except for the two facts only the operator can know
(AWS region + cluster).

**Architecture:** Backend loads `maki.config.yaml` (path via `MAKI_CONFIG` env, default
`./maki.config.yaml`) with `yaml.safe_load` → a typed pydantic `AppConfig` validated at startup with
friendly errors. The existing `settings` singleton keeps its public attribute surface
(`settings.aws_region`, `settings.ecs_cluster`, `settings.repo_for`, …) but sources the infra/UI
fields from the YAML instead of hardcoded defaults — this keeps the ~15 existing call sites
unchanged. A new `GET /api/config` serves the UI-relevant subset; the SPA fetches it on boot.
Generic *logic* (matching functions, grouping, timeline phase-building) stays in code; only *data*
moves to config.

**Tech Stack:** Python 3.11, FastAPI, pydantic v2, pydantic-settings, `pyyaml` (new dep);
React 18 + Vite + TS, react-query.

**Reference docs:** `docs/plans/2026-06-06-config-layer-design.md` (design spec),
`docs/plans/2026-06-06-security-posture-notes.md` (auth = localhost default, bind 127.0.0.1).

---

## Spec corrections from ground-truth (the code has evolved)

Apply these — they override the design spec where they conflict:

1. **Drop the `links` config block.** `app-sidebar.tsx` no longer has hardcoded GitHub/AWS-console
   links (only nav items + the "maki" wordmark). No consumer → don't build it.
2. **Drop the `user` config block.** `nav-user.tsx` already renders the live AWS identity from
   `/api/identity` (no `user@example.com` anywhere). The only literal left is the `"production"` env pill
   → replace with a single `envLabel` string in config.
3. **Amplify is already conditional in the ingester** (`ingest/service.py:269` guards on
   `settings.amplify_app_id` truthiness). Only `inventory/service.py` unconditionally appends the
   web-app row → that's the real change. Switch both to the new `amplify.enabled` flag.
4. **`/ecs/{service}-production` log-group convention** lives in `frontend/src/lib/aws-console.ts`
   (`logGroupForService`) and `DEFAULT_AWS_REGION = "eu-west-1"`. These are the real frontend infra
   literals to parameterize (not the files the external plan named).

## Final config schema (authoritative for this plan)

```yaml
# maki.config.yaml
# ── REQUIRED ──
aws:
  region: eu-west-1
  ecsCluster: production
  logGroupTemplate: "/ecs/{service}-production"   # optional; this default ships

# ── ALL OPTIONAL below ──
github:
  repos:
    - repo: acme/platform
      services: [inventory, wfm-service, newsfeed, nlabour]
    - repo: acme/middleware
      services: [middleware]
    - repo: acme/web-app
      services: [web-app]

amplify:
  enabled: true
  appId: dexampleapp123
  branch: master
  serviceName: web-app

branding:
  appName: maki

# Core ships the FULL vanilla shadcn palette in index.css. This block overrides ONLY the tokens
# listed, via a generated <style> the config provider injects (`:root{}` for light, `.dark{}` for
# dark). Omit `theme` entirely → pure vanilla shadcn. Values must match index.css's color space
# (Tailwind v4 = oklch). Keys are validated against an allowlist of shadcn tokens.
theme:
  light:
    primary: "oklch(0.52 0.24 280)"          # Nory violet (illustrative)
    primary-foreground: "oklch(0.98 0 0)"
    ring: "oklch(0.52 0.24 280)"
    sidebar-primary: "oklch(0.52 0.24 280)"
    radius: "0.75rem"                        # Nory's distinct rounding (any --radius value)
  dark:
    primary: "oklch(0.62 0.22 280)"

envLabel: production          # the pill in the sidebar footer

grouping:
  rules:
    - { match: "prod-workforce-payroll-", label: Payroll }
    - { match: "wfm-service", label: Workforce, exact: true }
    # … (Nory taxonomy moves here from domains.ts)

deployTimeline:
  enabled: true
  github:
    groupMatrixJobs: true
    hideJobsStartingWith: ["deploy-"]
    hideJobsEndingWith: ["deploy", "schedule"]
```

`grouping.rules` keep the existing `{match, label, exact?}` shape that `serviceDomain()` already
consumes (note: the code field is `domain`, rename to `label` consistently across config + the TS
type). The neutral shipped default for `grouping.rules` is `[]` (everything → "Other").

---

## Task 0 — Branch setup *(done by orchestrator, not a subagent)*

- [ ] `git checkout -b oss/config-layer` off `main`.
- [ ] Add `pyyaml` to `backend/requirements.txt` + `pyproject.toml` deps.

---

## Task 1 — Backend config foundation (YAML loader + `AppConfig` + settings shim)

**Why first:** everything else reads from this. Nothing downstream can move until the config object
exists and `settings` sources from it.

**Files:**
- Create: `backend/src/maki/config.py` (the `AppConfig` pydantic models + `load_config()`).
- Modify: `backend/src/maki/settings.py` (load YAML; expose infra fields from it; keep operational
  env fields; drop Nory literal defaults).
- Create: `backend/tests/test_config.py`.
- Create: `maki.config.example.yaml` (repo root, fully commented — every field one-line explained).

**Definition:**
- `AppConfig` models the schema above. `aws.region` + `aws.ecsCluster` are **required** (no default).
  Everything else optional with neutral defaults (`grouping.rules: []`, `amplify.enabled: False`,
  `branding.appName: "Deploy Dashboard"`, `theme: None` (→ pure vanilla shadcn, no overrides),
  `envLabel: "production"`, `aws.logGroupTemplate: "/ecs/{service}-production"`,
  `deployTimeline.enabled: True`, timeline github knobs default to the Nory-shaped values so behavior
  is unchanged for the existing instance).
- **Theme model:** `theme.light` / `theme.dark` are maps of shadcn-token → string value. Validate
  keys against an **allowlist** of shadcn tokens (`background`, `foreground`, `card`,
  `card-foreground`, `popover`, `popover-foreground`, `primary`, `primary-foreground`, `secondary`,
  `secondary-foreground`, `muted`, `muted-foreground`, `accent`, `accent-foreground`, `destructive`,
  `border`, `input`, `ring`, `radius`, `chart-1`..`chart-5`, `sidebar`, `sidebar-foreground`,
  `sidebar-primary`, `sidebar-primary-foreground`, `sidebar-accent`, `sidebar-accent-foreground`,
  `sidebar-border`, `sidebar-ring`). Unknown key → `ConfigError` naming the bad token. Values are
  opaque strings (must match index.css's color space — Tailwind v4 oklch; documented in the example,
  not validated).
- `load_config()`: read path from `MAKI_CONFIG` env (default `maki.config.yaml`); `yaml.safe_load`;
  validate into `AppConfig`. On missing file or validation error → raise a clear `ConfigError` with a
  message naming the field + pointing at `maki.config.example.yaml` (no traceback-as-UX).
- `settings.py`: keep operational env fields (`database_url`, `swr_*`, `ingest_*`, `github_token`,
  `github_api_url`, `static_dir`). The infra/UI fields (`aws_region`, `ecs_cluster`,
  `amplify_*`, repo resolution, timeline knobs, branding, grouping, envLabel) become properties/values
  sourced from the loaded `AppConfig`. Preserve the existing public names where call sites use them
  (`settings.aws_region`, `settings.ecs_cluster`) to avoid ripple.

**Acceptance:**
- `test_config.py` covers: required-field-missing → `ConfigError` with a useful message; a minimal
  valid config (aws only) loads with all optional defaults; a full config round-trips.
- `pytest backend/tests/test_config.py` green.
- App still imports (`from maki.api import app`) when `MAKI_CONFIG` points at a valid file.

**Test scope:** `pytest backend/tests/test_config.py -v` only.

---

## Task 2 — Service→repo resolution (`repos` list → `repo_for() -> str | None`)

**Files:**
- Modify: `backend/src/maki/config.py` (reverse-index + `repo_for`).
- Modify: `backend/src/maki/settings.py` (`repo_for` delegates to config; **signature now
  `str | None`**).
- Modify: `backend/src/maki/inventory/service.py` (`_commit_url`, `_enrich` handle `None`).
- Modify: `backend/src/maki/timeline/routes.py:69` + `timeline/service.py` (handle `None` repo → no
  CI segments).
- Modify/Create tests: `backend/tests/test_config.py`, `backend/tests/inventory/*`,
  `backend/tests/timeline/*`.

**Definition:**
- Build `service → repo` reverse index from `github.repos` on load. Validate **one-repo-per-service**:
  a service under two repos → `ConfigError` ("`inventory` is listed under two repos").
- `repo_for(name)` returns the repo or `None` (unmapped → enrichment skipped). Remove
  `default_github_repo`/`github_repo_overrides`.
- Consumers: `inventory.service._commit_url` returns `None` when `repo_for` is `None` (guard before
  building the URL); `_enrich` returns early. `timeline` skips CI lookup when repo is `None`.

**Acceptance:** unmapped service produces a service row with no commit_url/enrichment and no error;
mapped service unchanged. Duplicate-service config → `ConfigError`. Narrow tests green.

**Test scope:** `pytest backend/tests/test_config.py backend/tests/inventory backend/tests/timeline -v`.

---

## Task 3 — Amplify optional (`amplify.enabled`)

**Files:**
- Modify: `backend/src/maki/aws/amplify_registry.py` (service name from config, not literal
  `"web-app"`).
- Modify: `backend/src/maki/inventory/service.py` + `inventory/routes.py` (skip web-app row when
  `amplify.enabled` is false — don't even construct the registry).
- Modify: `backend/src/maki/ingest/service.py:269` (gate on `amplify.enabled` instead of
  `amplify_app_id` truthiness).
- Tests: `backend/tests/inventory/*`, `backend/tests/aws/*` (amplify), `backend/tests/ingest/*`.

**Definition:** when `amplify.enabled` is false, `get_inventory()` returns only ECS services, no
web-app row, no Amplify client call, no error. When true, behavior unchanged but `serviceName`,
`appId`, `branch` come from config.

**Acceptance:** disabled → no amplify row, no `get_branch` call (assert via mock); enabled → row
present with configured service name. Narrow tests green.

**Test scope:** `pytest backend/tests/inventory backend/tests/aws backend/tests/ingest -v`.

---

## Task 4 — Deploy-timeline config + zero-config default

**Files:**
- Modify: `backend/src/maki/timeline/routes.py` (pass new config-derived params).
- Modify: `backend/src/maki/timeline/service.py` (`_is_rollout_job` reads
  `hideJobsStartingWith`/`hideJobsEndingWith`; `groupMatrixJobs` toggles the `(...)`-stripping group
  collapse; `enabled` flag short-circuits to no CI segments / hidden feature).
- Tests: `backend/tests/timeline/*`.

**Definition:**
- Map `deployTimeline.github.hideJobsEndingWith` → the old `rollout_suffixes`;
  `hideJobsStartingWith` → the hardcoded `startswith("deploy-")` (now configurable list).
- `groupMatrixJobs: false` → don't collapse matrix jobs (each job its own segment); `true` (default)
  → current behavior.
- Keep `_RUN_CLUSTER_GAP_SECONDS` + the `" / "` separator parsing as **internal defaults** (not
  config).
- `deployTimeline.enabled: false` → timeline endpoint returns empty segments (feature off).

**Acceptance:** with defaults, timeline output identical to today; with `hideJobsEndingWith: []`,
rollout jobs appear; with `groupMatrixJobs: false`, `test (0)`/`test (1)` stay separate. Narrow tests
green.

**Test scope:** `pytest backend/tests/timeline -v`.

---

## Task 5 — `GET /api/config` endpoint (UI subset)

**Files:**
- Create: `backend/src/maki/app_config/routes.py` (new router) + register in `api.py`.
- Modify: `backend/src/maki/schemas.py` (add `UiConfigResponse`).
- Tests: `backend/tests/test_app_config.py`.

**Definition:** `UiConfigResponse` carries: `appName`, `theme: {light: {...}, dark: {...}} | None`,
`envLabel`, `awsRegion`, `logGroupTemplate`, `amplifyEnabled`,
`groupingRules: [{match,label,exact}]`, `deployTimelineEnabled`. (No secrets, no repo map — repos
are backend-only.) Route returns it from the loaded config.

**Acceptance:** `GET /api/config` returns the configured values; default config returns neutral
values. Test green.

**Test scope:** `pytest backend/tests/test_app_config.py -v`.

---

## Task 6 — Backend title from config

**Files:** Modify `backend/src/maki/api.py:58` (`FastAPI(title=...)` ← `config.branding.appName`
+ " — Deploy Dashboard" or just appName). No new test (smoke via existing app import).

**Acceptance:** app title reflects `branding.appName`; no "Nory" literal in `api.py`.

**Test scope:** `pytest backend/tests/test_health.py -v` (smoke that app builds).

---

## Task 7 — Frontend: fetch `/api/config` on boot (config provider)

**Why before 8–10:** frontend consumers need the config in context.

**Files:**
- Create: `frontend/src/lib/config.ts` (types + `fetchAppConfig`) + a React context/provider
  (`frontend/src/components/config-provider.tsx`) mounted in `App.tsx`.
- Modify: `frontend/src/api.ts` (add `fetchAppConfig` + `AppConfig` type).
- Create: `frontend/src/lib/config.test.ts` / provider test.

**Definition:** fetch `/api/config` once on app boot via react-query; expose through a `useConfig()`
hook. Provide sensible fallback defaults so a render before the fetch resolves doesn't crash.

**Acceptance:** `useConfig()` returns the fetched values; vitest covers the hook + fallback.

**Test scope:** `cd frontend && npx vitest run src/lib/config.test.ts`.

---

## Task 8 — Frontend: grouping rules from config

**Files:**
- Modify: `frontend/src/lib/domains.ts` (delete the `DOMAIN_RULES` constant + rename `domain`→`label`
  in the type; keep `serviceDomain(name, rules)` as a pure function taking rules).
- Modify: `frontend/src/pages/ServicesPage.tsx` (pass `useConfig().groupingRules` into
  `serviceDomain`).
- Modify: `frontend/src/lib/domains.test.ts` (test the function with injected rules).

**Definition:** `serviceDomain` becomes `serviceDomain(name, rules)` — generic logic, no embedded
Nory data. Rules come from config. Unmatched → "Other".

**Acceptance:** grouping works with config-supplied rules; empty rules → all "Other". Test green.

**Test scope:** `cd frontend && npx vitest run src/lib/domains.test.ts`.

---

## Task 9 — Frontend: infra literals from config (region + log-group + env label + title)

**Files:**
- Modify: `frontend/src/lib/aws-console.ts` (`DEFAULT_AWS_REGION` + `logGroupForService` read from
  config — accept region + template as args, or read via a small config accessor). Keep the
  console-URL builder logic generic.
- Modify: `frontend/src/components/current-deploy-section.tsx:156` (pass config region/template into
  `cloudWatchLogsUrl`).
- Modify: `frontend/src/components/nav-user.tsx:74` (the `"production"` pill ← `useConfig().envLabel`).
- Modify: `frontend/index.html` (`<title>` neutralized; real title set at runtime from config in
  `App.tsx` via `document.title`).
- Tests: relevant `.test.tsx` (aws-console, nav-user if present).

**Acceptance:** no `eu-west-1` / `-production` / `"production"` literals left in these files; values
come from config. Tests green.

**Test scope:** `cd frontend && npx vitest run src/lib/` (+ any touched component tests).

---

## Task 10 — Frontend: de-brand (logo, wordmark, theme, storage key)

**Files:**
- Modify: `frontend/src/components/logo.tsx` (strip the Nory SVG mark → a neutral text wordmark or a
  generic glyph; drop `aria-label="Nory"` and the violet fill).
- Modify: `frontend/src/components/app-sidebar.tsx:47,52` (wordmark text ← `useConfig().appName`;
  tooltip too).
- Modify: `frontend/src/index.css` (strip the Nory overrides so the file holds the **full vanilla
  shadcn** palette as the baseline — including the default `--radius`; the Nory look arrives only via
  the injected theme, not from index.css).
- Create: `frontend/src/lib/theme-overrides.ts` (build a CSS string from `useConfig().theme` →
  `:root { --token: value; … } .dark { … }`, prefixing each allowlisted key with `--`).
- Modify: config provider (Task 7) / `App.tsx` to inject that CSS as a `<style id="maki-theme">`
  element appended after `index.css` on boot, so listed tokens override vanilla. Tokens not listed
  keep the vanilla default. `--radius` is just another token → border-radius is themable here too
  (Nory's distinct rounding lives in `theme.light.radius`).
- Modify: `frontend/src/components/theme-provider.tsx` (rename `maki-ui-theme` storage key → neutral,
  e.g. `app-ui-theme`).
- Tests: `theme-overrides.test.ts` (CSS generation: only provided tokens emitted, `--` prefix,
  light/dark scopes, empty/None → empty string), + any touched component tests.

**Acceptance:** no Nory SVG / violet / radius literal in the shipped default (index.css is vanilla
shadcn); `appName` drives the wordmark and the `theme` block (colors **and** `radius`) drives the
look at runtime via the injected stylesheet; omitting `theme` → pure vanilla. Tests + `tsc -b` +
`vite build` green.

**Test scope:** `cd frontend && npx vitest run && npx tsc -b && npx vite build`.

---

## Task 11 — Security default + OSS scaffolding

**Files:**
- Modify: `Dockerfile:21` (bind `127.0.0.1` instead of `0.0.0.0`).
- Modify: `.gitignore` (ignore `maki.config*.yaml` but **un-ignore** `maki.config.example.yaml` via
  `!maki.config.example.yaml` — so the real config + the nory-template are ignored, only the neutral
  example is tracked).
- Modify: `README.md` / docs (note: localhost-only default; `/api/services/{name}/env` exposes env
  **values**, not just names; do not expose the port — per security-posture-notes).
- Ensure `maki.config.example.yaml` (from Task 1) is complete + commented.

**Acceptance:** Docker binds localhost; real config gitignored; example committed; docs carry the
warning.

**Test scope:** none (config/docs); verify `git status` shows `maki.config.yaml` ignored.

---

## Task 12 — Nory real config + shareable internal template + live smoke test *(orchestrator-assisted)*

**Files:**
- Create (local, **gitignored**): `maki.config.yaml` — the real Nory values (region `eu-west-1`,
  cluster `production`, real `repos`, amplify `dexampleapp123`, the Nory grouping taxonomy lifted from
  the old `domains.ts`, the violet + `0.25rem` radius theme lifted from the old `index.css`, timeline
  knobs). This file IS the regression config + the seed for the shareable template.
- Create (local, **gitignored**): `maki.config.nory-template.yaml` — the **shareable internal
  template** for other Nory engineers. Same real Nory values, but:
  - a loud header: `# INTERNAL — contains Nory infra identifiers. Do NOT commit to the public repo
    or publish externally. Distribute via internal channels only.`
  - a one-line plain-English comment on **every** field (what it is, where to get the value, what
    happens if omitted) so a teammate can fill/adjust without reading code.
  - distributed out-of-band (the file is gitignored, so engineers who clone the repo won't get it
    automatically — share via internal drive/Slack/private repo).

**Definition:** with the real config in place, run backend + frontend against live AWS and confirm:
fleet board renders, a service detail + deploy timeline render, env tab works, grouping matches the
old behavior, the violet theme + tight radius render. This is the regression gate that the
extraction didn't break the working instance. Then verify the `nory-template.yaml` loads cleanly on
a fresh `MAKI_CONFIG` pointer (a teammate's first-run path).

**Guardrail:** both files MUST match a `.gitignore` rule (`maki.config*.yaml` except
`maki.config.example.yaml`). Confirm `git status` never shows either as trackable before finishing.

**Acceptance:** the running maki instance behaves identically to pre-refactor `main`; the
shareable template loads green and is fully commented; neither real file is git-trackable.

**Test scope:** manual smoke (backend `uvicorn`, frontend `vite`), plus full narrow test suites from
prior tasks re-run green.

---

## Self-review (orchestrator, before dispatch)

- **Spec coverage:** every design-spec block maps to a task (aws→T1, repos→T2, amplify→T3,
  timeline→T4, /api/config→T5, branding/grouping/envLabel→T5+T8+T10, security default→T11), minus the
  dropped `links`/`user` blocks (corrected above).
- **Type consistency:** `repo_for` is `str | None` from Task 2 onward; the grouping rule field is
  `label` (not `domain`) consistently in config + TS type from Task 8.
- **No silent caps:** the deploy-timeline `enabled:false` path and unmapped-repo path both degrade
  visibly (empty/skipped), matching existing fail-soft behavior.

## Out of scope (other projects)

Security hardening beyond the localhost bind (Project B); rename off "maki" (Project C); demo/fixture
mode; multi-CI-provider abstraction.

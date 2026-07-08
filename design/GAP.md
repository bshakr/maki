# Gap analysis — built vs wireframe

What you see today vs the wireframes, and which phase closes each gap. As of Phase 1 complete.

## Built (Phase 1) ✓

- **Shell** — sidebar-08, Nory brand lockup, nav, footer (user + env + dark toggle), breadcrumb, collapsible icon rail.
- **Services `/`** — grid, fleet summary, filter, status/platform badges, sha→commit links, 20s refresh, row→detail, skeleton/error.
- **Service detail `/services/:name`** — CURRENT block (status, sha, deployed-ago, run/des, image, CloudWatch + commit links).
- **Nory theme** — colors, system font, 4px radius, logo, favicon, semantic status colors.

## Missing / stubbed — by page

| Surface | Wireframe shows | Today | Closes in |
|---|---|---|---|
| Service detail — **DEPLOY HISTORY** card | per-deploy rows (sha, who, duration, status, roll-back-to) | disabled placeholder | **P2** |
| Service detail — **RECENT ACTIONS** card | rollback/run-task audit | placeholder — needs a ledger (preview actions don't execute, nothing to record) | **P2.5 ledger** |
| Service detail — **Roll back** / **Run task** buttons | open dialog/sheet | ✓ both wired (preview-only/inert) | **P3 / P4 done** |
| Service detail — **GitHub run** link | link to the deploy's Actions run | not present (needs ledger) | **P2** |
| **Activity** `/activity` | chronological deploy + action feed | "coming soon" stub | **P2 / P4** |
| **Metrics** `/metrics` | DORA stat cards + trend chart | ✓ real-only: deploy freq, total, median lead time + deploys/day chart, range/service filters | **P5 done** |
| **Rollback dialog** | confirm + dispatch + progress | not built | **P3** |
| **Run-task sheet** | command + run + logs | ✓ built (preview-only/inert; no task-def selector, no recent-runs — need ledger) | **P4 done** |
| Services — column **sorting** | sort by status/name/deployed | not built | P1 polish |
| Top-bar **global search** | search across services | per-grid filter only | P2+ |
| Services — **drift flag** (live vs ledger) | indicator | not built (needs ledger) | **P2** |

## Why the UI looks "less" than the wireframes

The wireframes describe the **finished product across all 5 phases**. Only **Phase 1** is built, so
Activity, Metrics, deploy history, rollback, and run-task are intentionally stubs/disabled. Nothing
is broken — those surfaces are scheduled work, not regressions.

## Phase plan (recap)

- **P1 — visibility** ✓ done.
- **P2 — deploy ledger + history**: persistence (SQLite), deploy-history ingest → service-detail HISTORY card, Activity deploy feed, GitHub run links, drift flag.
- **P3 — rollback**: rollback dialog + GitHub `workflow_dispatch` action plane.
- **P4 — one-off tasks** ✓ partial: run-task sheet built **preview-only/inert** (echo-only backend,
  no ECS run-task / dispatch / AWS write). Deferred to the ledger (P2.5): RECENT ACTIONS card,
  Activity action events, task-def selector, recent-runs list — all need persisted action records.
- **P5 — DORA metrics** ✓ done (real-only): Metrics page — deploy freq, total deploys, median
  lead time (commit→deploy) + deploys/day bar chart, range (7/30/90d) + service filters. ECS-only.
  MTTR / change-fail / rollback count **omitted** — need a deploy ledger + incident source.

Plus a small **P1-polish** backlog: column sorting, global search.

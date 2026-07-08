# Services overview — `/`

**Phase:** P1 · **Status:** built

The home page and the core incident-response view: every prod service at a glance with its live
git SHA, deploy recency, running/desired tasks, and rollout health.

```
┌─────────────┬──────────────────────────────────────────────────────────┐
│ ◆ maki    » │  Services                          [🔍 filter]  prod ▾   │
│ ▤ Services  ├──────────────────────────────────────────────────────────┤
│ ▸ Activity  │  42 services   ●39 healthy  ◐2 deploying  ✕1 error  upd 4s│
│ ▣ Metrics   │ ┌──────────────────────────────────────────────────────┐ │
│             │ │ Service       Plat SHA      Deployed Run/Des Status   │ │
│             │ ├──────────────────────────────────────────────────────┤ │
│             │ │ ●wfm-service  ecs a1b2c3d↗ 2h ago   4/4   [COMPLETED] │ │
│             │ │ ◐inventory    ecs 9f8e7d6↗ 3m ago   2/3   [IN_PROG…]  │ │
│             │ │ ●newsfeed     ecs c3d4e5f↗ 1d ago   2/2   [COMPLETED] │ │
│             │ │ ✕pos-ingestion ecs —       —        0/2   [error]     │ │
│ ─────────── │ │ ●web-app      amp beef123↗ 5h ago   —     [SUCCEED]   │ │
│ 👤 bailey ▾ │ └──────────────────────────────────────────────────────┘ │
└─────────────┴──────────────────────────────────────────────────────────┘
```

## Elements

- **Fleet summary** — total count + healthy / deploying / error tallies. Health derived:
  error if status is null/error/FAILED/unavailable OR running<desired; deploying if IN_PROGRESS; else healthy.
- **Filter** — client-side substring filter on service name.
- **Table** (shadcn `Table`) columns:
  - Service — name (row links to `/services/:name`).
  - Platform — `Badge` ("ecs" / "amp").
  - SHA — short 7-char, external link to the GitHub commit when `commit_url` present.
  - Deployed — relative time (`ago`).
  - Running / Desired — `{running} / {desired}`.
  - Status — semantic `Badge` (COMPLETED/SUCCEED→success green, IN_PROGRESS→violet, FAILED/error→destructive).
- **"updated Ns ago"** caption; auto-refresh every 20s.

## Data

`GET /api/services` → `{ services: DeployedService[], generated_at }`. Live AWS query, TTL-cached.

## States

Loading → skeleton rows. Error → alert. Empty → "No services deployed" / "No services match".

## Not yet (later phases)

- Global top-bar search (P2+) — currently per-grid filter only.
- Column sorting (P1 polish).
- Drift flag (live AWS vs ledger) — needs the ledger (P2).

# Activity — `/activity`

**Phase:** P2 (deploys) · P4 (actions) · **Status:** stub (placeholder page only)

A single chronological feed of everything happening across the fleet: deploys (P2) and operator
actions like rollbacks/run-tasks (P4). The "what just changed?" view during an incident.

```
┌─────────────┬──────────────────────────────────────────────────────────┐
│ ◆ maki    » │  Activity                  type:[all▾]  service:[all▾]    │
│ ▤ Services  ├──────────────────────────────────────────────────────────┤
│ ▸ Activity  │ 2h   ● deploy    wfm-service    a1b2c3d  CI     12m  ✓     │
│ ▣ Metrics   │ 3m   ◐ deploy    inventory      9f8e7d6  CI      —   …     │
│             │ 1d   ▸ rollback  wfm-service   →7e6d5c4  bailey      ✓     │
│             │ 2d   ✕ deploy    pos-ingestion  4b3a2c1  CI      3m  ✕     │
│             │ 3d   ▸ run-task  inventory      migrate   bailey      ✓     │
│ ─────────── │                                                            │
│ 👤 bailey ▾ │                                                            │
└─────────────┴──────────────────────────────────────────────────────────┘
```

## Elements

- **Feed rows** — relative time, type icon (deploy/rollback/run-task), service, sha or target,
  actor, duration, outcome. Row → service detail.
- **Filters** — by type (deploy / rollback / run-task) and by service.

## Data

P2: `GET /api/activity` (deploys from the ledger). P4: merges action events.

## Build note

Currently `ActivityPage.tsx` renders only a "coming soon" placeholder. Real feed lands in P2 once
the ledger exists; action events added in P4.

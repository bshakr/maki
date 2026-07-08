# Service detail — `/services/:name`

**Phase:** P1 (CURRENT block) · P2 (history) · P4 (actions) · **Status:** partial — CURRENT built; HISTORY + ACTIONS are disabled placeholders

Drill-in for a single service: what's live now, how it got here, and what you can do about it.

```
┌─────────────┬──────────────────────────────────────────────────────────┐
│ ◆ maki    » │  Services / wfm-service          [Roll back] [Run task]   │
│ ▤ Services  ├──────────────────────────────────────────────────────────┤
│ ▸ Activity  │  CURRENT                                          [P1 ✓]   │
│ ▣ Metrics   │   ● COMPLETED  a1b2c3d↗github  deployed 2h ago  4/4       │
│             │   image …/wfm-service:a1b2c3d   cluster production         │
│             │   [GitHub run ↗*]   [CloudWatch logs ↗]                    │
│             │ ┌──────────────────────────────────────────────────────┐ │
│             │ │ DEPLOY HISTORY                                 [P2]   │ │
│             │ │  ● a1b2c3d 2h ago  CI     12m COMPLETED [roll back to]│ │
│             │ │  ● 7e6d5c4 1d ago  bailey  9m COMPLETED [roll back to]│ │
│ ─────────── │ │  ✕ 4b3a2c1 2d ago  CI      3m FAILED                  │ │
│ 👤 bailey ▾ │ ├──────────────────────────────────────────────────────┤ │
│             │ │ RECENT ACTIONS                                 [P4]   │ │
│             │ │  ▸ rollback → 7e6d5c4  bailey 1d ago  ✓ [logs↗]      │ │
│             │ └──────────────────────────────────────────────────────┘ │
└─────────────┴──────────────────────────────────────────────────────────┘
```
\* GitHub *run* link needs the ledger (P2). GitHub *commit* link works now.

## Elements

- **CURRENT card** [P1 ✓] — status badge, SHA→commit link, deployed-ago, running/desired, image, platform, CloudWatch logs deep-link (built from name + region), commit link.
- **Header actions** — `Roll back` / `Run task` buttons. Currently rendered **disabled** ("coming in a later phase").
- **DEPLOY HISTORY card** [P2] — per-deploy rows: sha, deployed-ago, who triggered, duration, status, "roll back to" affordance. Currently a disabled placeholder.
- **RECENT ACTIONS card** [P4] — audit of rollbacks/run-tasks for this service. Currently a disabled placeholder.

## Data

P1: filters the `GET /api/services` payload client-side by `:name`. P2: `GET /api/services/:name/deployments`. P4: `GET /api/services/:name/actions`.

## States

Loading → skeleton. Unknown name → "Service not found" + back link.

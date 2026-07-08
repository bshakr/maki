# Metrics — `/metrics`

**Phase:** P5 · **Status:** ✓ built (real-only metric set — see Build note)

DORA-style delivery metrics derived from the deploy ledger — to see trends and improve the pipeline.

```
┌─────────────┬──────────────────────────────────────────────────────────┐
│ ◆ maki    » │  Metrics             range:[30d▾]      service:[all▾]     │
│ ▤ Services  ├──────────────────────────────────────────────────────────┤
│ ▸ Activity  │  Deploy freq   Lead time    Change-fail    MTTR           │
│ ▣ Metrics   │  8.2 /day      3h12m med    4.1%           46m            │
│             │ ┌── deploys over time ───────────────────────────────┐    │
│             │ │        ▇   ▇▇                                       │    │
│             │ │  ▂▅▇ ▇▇▇▇ ▇▇▇  ▅▂                                   │    │
│             │ └────────────────────────────────────────────────────┘    │
│             │  Rollbacks (30d): 11      Deploys (30d): 247              │
│ ─────────── │                                                            │
│ 👤 bailey ▾ │                                                            │
└─────────────┴──────────────────────────────────────────────────────────┘
```

## Elements

- **Stat cards** — deploy frequency, lead time (sha→live), change-fail rate (rollbacks/deploys), MTTR.
- **Trend chart** — deploys over time (shadcn chart, chart-* theme tokens already defined).
- **Filters** — time range + service.

## Data

`GET /api/metrics?range=&service=` aggregated from the ledger (needs P2 ledger first).

## Build note

Built **real-only** (no persistent ledger exists). Metrics are derived from ECS task-def revisions
(the deploy timeline) + GitHub commit timestamps, aggregated fleet-wide by `MetricsService` →
`GET /api/metrics?range_days=&service=`. Shipped: deploy frequency, total deploys, median lead time
(commit `committed_at` → `registered_at`), deploys/day bar chart, range (7/30/90d) + service filters.

**Omitted** (need data we don't have): rollback count / change-fail rate (no rollback ledger — the
rollback endpoint is inert preview), and MTTR (no incident source). Amplify excluded (no revision
timeline). These light up once a deploy ledger lands (P2.5).

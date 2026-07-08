# maki — design

Wireframes + page specs for the maki deploy console. ASCII wireframes are the source of intent;
the built UI should converge on these. Each page file notes its **phase** and **build status**.

## Information architecture

```
maki
├── /                  Services overview (grid)        → 01-services.md          [P1]
├── /services/:name    Service detail                  → 02-service-detail.md    [P1 current / P2-4 rest]
├── /activity          Global deploy + action feed     → 03-activity.md          [P2 / P4]
└── /metrics           DORA charts                     → 04-metrics.md           [P5]
   dialogs/sheets:
   ├── Rollback confirm                                → 05-rollback-dialog.md   [P3]
   └── Run one-off task                                → 06-run-task-sheet.md    [P4]
```

## Shell (all pages)

Collapsible **shadcn sidebar-08** on the left (brand lockup: Nory mark + "maki"; nav Services /
Activity / Metrics; footer: user + env "production" + dark-mode toggle; collapses to an icon rail).
Content renders in `SidebarInset` with a sticky header = sidebar trigger + route breadcrumb.

```
┌─────────────┬──────────────────────────────────────────────────────────┐
│ ◆ maki    » │  ‹breadcrumb›                                   ‹actions› │
│ ▤ Services  ├──────────────────────────────────────────────────────────┤
│ ▸ Activity  │                                                            │
│ ▣ Metrics   │   ‹page content (Outlet)›                                  │
│             │                                                            │
│ ─────────── │                                                            │
│ 👤 bailey ▾ │                                                            │
└─────────────┴──────────────────────────────────────────────────────────┘
```

## Phase legend

- **P1 — read-only visibility** (DONE): shell, services grid, service-detail CURRENT block, Nory theme.
- **P2 — deploy ledger + history**: persistence, deploy history (service-detail HISTORY card), Activity feed (deploys).
- **P3 — rollback**: rollback dialog + action plane (GitHub workflow_dispatch).
- **P4 — one-off tasks**: run-task sheet, service-detail RECENT ACTIONS, Activity (actions).
- **P5 — DORA metrics**: Metrics page charts.

See `GAP.md` for built-vs-wireframe status.

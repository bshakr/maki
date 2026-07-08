# Rollback dialog

**Phase:** P3 · **Status:** not built (Roll back button is disabled on service detail)

Confirm + execute a rollback to a previous known-good SHA. Opens from the service-detail
`Roll back` button (or a history row's "roll back to"). This is the **action plane** — a real prod
write — so it goes through GitHub Actions (`workflow_dispatch`), never a direct AWS write from maki.

```
┌──────────────────── Roll back · wfm-service ─────────────────────┐
│ Current   a1b2c3d   (2h ago)                                     │
│ Target  ▾ 7e6d5c4 — "fix tax calc" — 1d ago, COMPLETED          │
│                                                                  │
│ ⚠ Deploys 7e6d5c4 to production via GitHub Actions.             │
│   Logged as you (bailey).                                        │
│                            [Cancel]      [Roll back ▸]          │
└──────────────────────────────────────────────────────────────┘
        ↓ after confirm
┌──────────────────── Rolling back… ──────────────────────────────┐
│ ▸ dispatched GH run #4821 ↗   ◐ deploying…  (polling status)     │
└──────────────────────────────────────────────────────────────┘
```

## Elements

- shadcn `Dialog`. Current SHA (read-only) + target SHA selector (from deploy history, defaults to
  last COMPLETED before current). Warning line. Cancel / confirm.
- After confirm: progress state showing the dispatched GitHub run + polled status.

## Behaviour / data

`POST /api/services/:name/rollback { target_sha }` → maki calls GitHub `workflow_dispatch` on a
rollback workflow in the target repo (nory / Node-Middleware), then polls the run. Actor recorded.

## Dependencies

Needs P2 (history to pick a target) and GitHub API write wiring + a rollback workflow in the repos.

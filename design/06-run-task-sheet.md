# Run one-off task sheet

**Phase:** P4 · **Status:** ✓ built **preview-only/inert** — opens from the service-detail "Run
task" button. Backend `POST /api/services/{name}/run-task` echoes the request back with
`executed=false` and performs NO action (no ECS run-task, no dispatch, no AWS write, no subprocess).
Deferred (need ledger): task-def selector, recent-runs list, RECENT ACTIONS card, Activity events.

Run an ad-hoc command in prod (migration, backfill, script) against a service's task definition —
safely and audited. Opens from the service-detail `Run task` button. Like rollback, it executes via
GitHub Actions / ECS run-task, not a direct write from maki.

```
┌──────────────── Run one-off task · wfm-service ────────────────┐
│ Command  [ python -m scripts.backfill --since 2026-05-01     ] │
│ Task def   wfm-service:a1b2c3d (current)        ▾              │
│ ⚠ Runs in production. Logged as bailey.                       │
│                              [Cancel]     [Run ▸]            │
│ ─────────────────────────────────────────────────────────── │
│ Recent:  ▸ migrate  bailey 3h ago  ✓  [logs ↗]               │
└────────────────────────────────────────────────────────────────┘
```

## Elements

- shadcn `Sheet` (or `Dialog`). Command input, task-def selector (default current), warning, run.
- Recent runs list with status + CloudWatch logs link.

## Behaviour / data

`POST /api/services/:name/run-task { command, task_def }` → dispatches a run-task workflow / ECS
run-task with a command override; surfaces the CloudWatch logs link; polls status into RECENT ACTIONS.

## Dependencies

GitHub API write wiring (shared with P3) + a run-task workflow; the service-detail RECENT ACTIONS
card (P4) and Activity actions feed (P4) read from the same action records.

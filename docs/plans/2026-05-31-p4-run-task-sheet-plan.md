# P4 — Run-task sheet (preview-only) implementation plan

**Goal:** Add a one-off-task runner UI to the service-detail page, opened from the (currently
disabled) "Run task" button. Like rollback, it is **preview-only / inert** — it shows what a run
WOULD do and performs NO action.

**SAFETY MANDATE (non-negotiable):** Running an arbitrary command in production is MORE dangerous
than a rollback. The backend endpoint is physically incapable of touching production: NO ECS
`run_task`, NO GitHub `workflow_dispatch`, NO AWS write, NO subprocess, NO side effect of any kind.
It echoes the request back as an inert preview. Mirror `backend/src/maki/rollback/routes.py` exactly.
Tests are fully mocked, zero network.

**Architecture:** Inert `POST /api/services/{name}/run-task` returning a `RunTaskPreview`. Frontend
`RunTaskSheet` (shadcn `Sheet`, already installed) opened from the service-detail page; command
input + current task-def display + warning + type-service-name-to-confirm gate + "Preview run"
button that calls the inert endpoint and renders the preview result.

**Tech stack:** FastAPI + pydantic v2 (backend); React + TanStack-free local state + shadcn Sheet
(frontend), mirroring `rollback-dialog.tsx`.

**Scope:**
- ✅ Inert run-task endpoint + RunTaskSheet wired into service detail (enable the button).
- ❌ RECENT ACTIONS card — stays the existing `PlaceholderCard("Recent actions")`. Real recent-runs
  + Activity action events need a deploy/action **ledger** (P2.5); preview runs don't execute, so
  there is nothing to record. Do NOT fabricate a recent-runs list.
- ❌ Task-def SELECTOR (choose a non-current def) — show the CURRENT task def read-only for now;
  a selector is deferred (it implies real execution targeting). Keep it simple + honest.

---

## Pinned API contract (both agents implement THIS exactly)

`POST /api/services/{name}/run-task`

Request body (`RunTaskRequest`):
```json
{ "command": "python -m scripts.backfill --since 2026-05-01", "task_def": "newsfeed:1987" }
```
- `command`: str, required, non-empty.
- `task_def`: str | None, optional (the current task def the UI is previewing against).

Response (`RunTaskPreview`):
```json
{
  "service": "newsfeed",
  "command": "python -m scripts.backfill --since 2026-05-01",
  "task_def": "newsfeed:1987",
  "executed": false,
  "message": "Preview only — run-task execution is not implemented. No production change was made."
}
```
`executed` is ALWAYS `false`.

---

## Task T1 (backend): inert run-task endpoint

**Files:**
- Modify: `backend/src/maki/schemas.py` (add `RunTaskPreview`)
- Create: `backend/src/maki/run_task/__init__.py`
- Create: `backend/src/maki/run_task/routes.py`
- Modify: `backend/src/maki/api.py` (include router BEFORE `mount_spa`)
- Test: `backend/tests/run_task/__init__.py`, `backend/tests/run_task/test_routes.py`

Schema (`schemas.py`, mirror `RollbackPreview`):
```python
class RunTaskPreview(BaseModel):
    service: str
    command: str
    task_def: str | None = None
    executed: bool = False
    message: str
```

Route (`run_task/routes.py`) — mirror `rollback/routes.py` EXACTLY, including the SAFETY comment:
```python
from fastapi import APIRouter
from pydantic import BaseModel

from maki.schemas import RunTaskPreview

router = APIRouter(prefix="/api")


class RunTaskRequest(BaseModel):
    command: str
    task_def: str | None = None


@router.post("/services/{name}/run-task", response_model=RunTaskPreview)
def run_task(name: str, body: RunTaskRequest) -> RunTaskPreview:
    # SAFETY: UI-ONLY PREVIEW. This endpoint intentionally performs NO action:
    # no ECS run_task, no GitHub dispatch, no subprocess, no AWS call, no side effect of any kind.
    # Real run-task execution is deliberately not implemented.
    return RunTaskPreview(
        service=name,
        command=body.command,
        task_def=body.task_def,
        executed=False,
        message=(
            "Preview only — run-task execution is not implemented. No production change was made."
        ),
    )
```

Wire in `api.py`: `from maki.run_task.routes import router as run_task_router` + `app.include_router(run_task_router)` alongside the other routers (before `mount_spa`).

Tests (FastAPI `TestClient`, mirror the rollback route test):
- [ ] POST returns 200, `executed is False`, echoes `service`/`command`/`task_def`, message contains "Preview only".
- [ ] `task_def` omitted → defaults to `null`, still `executed False`.
- [ ] (Inertness is structural — assert the response and that no client/AWS object is involved; there is nothing to mock because the endpoint has no dependencies.)
- [ ] Run `python -m pytest -q` from `backend/`. All green.

## Task T2+T3 (frontend): api client + RunTaskSheet + wire into service detail

**Files:**
- Modify: `frontend/src/api.ts` (types + `runTaskPreview`)
- Create: `frontend/src/components/run-task-sheet.tsx`
- Modify: `frontend/src/pages/ServiceDetailPage.tsx` (enable button, open sheet)
- Test: `frontend/src/components/run-task-sheet.test.tsx`

### api.ts (implements pinned contract)
```ts
export interface RunTaskPreview {
  service: string;
  command: string;
  task_def: string | null;
  executed: boolean;
  message: string;
}
export async function runTaskPreview(
  name: string,
  command: string,
  taskDef: string | null,
): Promise<RunTaskPreview> {
  const r = await fetch(`/api/services/${encodeURIComponent(name)}/run-task`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command, task_def: taskDef }),
  });
  if (!r.ok) throw new Error(`Run-task preview failed: ${r.status}`);
  return r.json();
}
```

### run-task-sheet.tsx — MIRROR `rollback-dialog.tsx` conventions (study it first)
Use shadcn `Sheet` (`@/components/ui/sheet`): `Sheet`, `SheetContent`, `SheetHeader`, `SheetTitle`,
`SheetDescription`, `SheetFooter`. Props:
```ts
{ open: boolean; onOpenChange: (open: boolean) => void; service: string; taskDef: string | null; }
```
Layout (preview-only posture, like the rollback dialog):
- Title: "Run task · {service}" + a `Badge variant="secondary"` "PREVIEW".
- A destructive `Alert` (AlertTriangle): "Preview only — execution is intentionally not implemented.
  Nothing runs in production."
- Command field: a `Textarea` (install via `npx shadcn@latest add textarea` if not present;
  otherwise use `Input`) labelled "Command", monospace, placeholder e.g.
  `python -m scripts.backfill --since 2026-05-01`.
- Task def: read-only line showing `taskDef ?? "current"` (muted), labelled "Task definition".
- Type-`{service}`-to-confirm `Input` gate (same pattern + copy as rollback-dialog).
- Footer: ONLY a "Preview run" button (top-right X closes the sheet; no Close button — matches
  rollback dialog). Disabled until the confirm name matches AND command is non-empty.
- On click: `runTaskPreview(service, command, taskDef)`; render the returned message in an
  informational `Alert` (Info icon) — "Preview only — no production change was made." + message.
  Reset transient state when the sheet (re)opens (mirror the rollback dialog's `useEffect([open])`).

### ServiceDetailPage.tsx
- Import `RunTaskSheet`. Add `runTaskOpen` state.
- Replace the disabled "Run task" `Button` (lines ~371-378) with one that is enabled when
  `currentSvc` exists and opens the sheet (`onClick={() => setRunTaskOpen(true)}`, drop `disabled`
  + the "Coming in a later phase" title).
- Render `<RunTaskSheet open={runTaskOpen} onOpenChange={setRunTaskOpen} service={currentSvc.name}
  taskDef={null} />` next to the existing `<RollbackDialog>` (only when `currentSvc`).
- Leave the `PlaceholderCard title="Recent actions"` UNCHANGED.

Tests (vitest + renderWithProviders + mocked `runTaskPreview`):
- [ ] Sheet renders title + PREVIEW badge + preview-only warning.
- [ ] "Preview run" disabled until service name typed AND command non-empty; enabled when both set.
- [ ] Clicking "Preview run" calls `runTaskPreview` with the typed command and renders the returned
      message.
- [ ] `npx vitest run` green (all existing + new) + `npm run build` green.

---

## Execution order
1. Parallel: T1 (backend agent, backend/ only) ∥ T2+T3 (frontend agent, frontend/ only). Both honor
   the pinned contract. No file overlap.
2. Controller verifies each: HEAD advanced, tests/build green, endpoint inert (grep for absence of
   any execute/dispatch/run_task-AWS call).

Each task: subagent runs plan → implement → `/code-review` → fix → local commit. No push.

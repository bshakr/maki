# Accurate history lead time via ECS service deployments

**Goal:** show each deploy-history row's real "merged → fully in production" lead time, using ECS's
`ListServiceDeployments`/`DescribeServiceRevisions` to get the deployment `finishedAt` per revision —
no ledger. Bounded by ECS's 90-day service-deployment retention (deploys on/after 2024-10-25); rows
outside that window simply show no lead time.

**Why this is correct (not registered_at):** `finishedAt` from a ECS service deployment is the moment
the rollout fully completed in production. Lead time = `finishedAt − committed_at` (committer time ≈
merge time). Previous attempt used `registered_at` (rollout START) — wrong; that's been removed.

**Tech:** boto3 ECS (read-only), FastAPI/pydantic, React. All tests mocked, zero network.

---

## Task 1 (backend): finished_at per revision from service deployments

**Files:**
- Create `backend/src/maki/aws/service_deployments.py`
- Modify `backend/src/maki/schemas.py` (`DeployRecord` add `finished_at`)
- Modify `backend/src/maki/history/service.py` (populate `finished_at`)
- Modify `backend/src/maki/history/routes.py` if wiring a new dep
- Tests under `backend/tests/`

`ECSServiceDeployments` (new, in `aws/service_deployments.py`):
- Constructor takes the ecs `client` + `cluster`.
- `finished_at_by_revision(self, service_name: str, since: datetime, family: str) -> dict[int, datetime]`:
  1. Paginate `list_service_deployments(cluster=, service=service_name, createdAt={"after": since})`
     (newest first is fine). Collect each brief's `(targetServiceRevisionArn, finishedAt, status)`;
     keep only entries with a non-null `finishedAt` (any completed status — SUCCESSFUL or
     ROLLBACK_SUCCESSFUL etc. all mean "this revision reached prod at finishedAt").
  2. Batch-resolve the revision ARNs to task definitions via
     `describe_service_revisions(serviceRevisionArns=[...])` (max 20 per call) →
     each `serviceRevisions[].taskDefinition` (an ARN like `…:task-definition/<family>:<rev>`).
     Parse the trailing `:<rev>` to an int (reuse `ECSDeployHistory._revision_from_arn` /
     `family_from_arn` style parsing — extract a shared `revision_from_arn` helper if cleaner).
  3. Return `{revision_int: finished_at}`. If a revision appears twice, keep the EARLIEST finishedAt
     (first time it reached prod).
- **Defensive:** wrap the whole thing so ANY failure (the API unsupported by the installed boto3,
  `AccessDeniedException`, `UnsupportedFeatureException`, throttling, parse failure) → return `{}` and
  log a warning. History MUST still render without lead time if this fails. Do not raise.

`schemas.py`: add `finished_at: datetime | None = None` to `DeployRecord` (after `committed_at`).

`HistoryService`:
- Inject an `ECSServiceDeployments` (or build it from the existing ecs client + cluster).
- In `_compute(service_name)`, after building + enriching records: compute
  `since = now - 90 days`; call `finished_at_by_revision(service_name, since, family)`; for each
  record set `record.finished_at = map.get(record.revision)` when present.
- Keep this cost on the per-service history path only (NOT inventory/activity/metrics).

`history/routes.py`: construct the new dep with `ecs_client()` + `settings.ecs_cluster`, pass into
`HistoryService` (mirror existing wiring).

**Tests (mocked):**
- `ECSServiceDeployments.finished_at_by_revision`: fake client where `list_service_deployments`
  paginator yields briefs (one SUCCESSFUL w/ finishedAt + target rev arn, one IN_PROGRESS w/ null
  finishedAt → excluded), and `describe_service_revisions` maps arns → task def arns → assert the
  `{revision: finished_at}` map (excludes the unfinished one; parses revision correctly).
- Failure isolation: `list_service_deployments` raising → returns `{}` (no raise), warning logged.
- `HistoryService._compute` sets `finished_at` on the matching record and leaves it None for
  revisions absent from the map. Inject a fake clock for `since`.
- Full `python -m pytest -q` green.

## Task 2 (frontend): show the accurate history lead time

**Files:** `frontend/src/api.ts`, `frontend/src/pages/ServiceDetailPage.tsx`, tests.

- `api.ts`: add `finished_at: string | null;` to `DeployRecord` (after `committed_at`).
- `ServiceDetailPage.tsx` `DeployHistoryItem`: re-import `formatDuration` + `leadTimeSeconds` from
  `@/lib/format`; append the lead time to the meta line ONLY when
  `leadTimeSeconds(d.committed_at, d.finished_at)` is non-null:
  `sha · author · ago · {formatDuration(...)}` with a `title="merged → live"`. (Uses `finished_at`
  now, NOT `registered_at`.)
- Tests (`ServiceDetailPage.test.tsx`): give a history fixture row a `finished_at` 3h after its
  `committed_at` → assert "3h 0m" appears in a history card; a row with null `finished_at` → no lead
  time appended (no "· —"). Keep the current-deploy tile test + all others green.
- `npx vitest run` + `npm run build` green.

---

## Notes
- 90-day / 2024-10-25 retention means many older rows legitimately show no lead time — that's honest,
  not a bug.
- Do NOT touch the Metrics page lead time here (fleet-wide finishedAt is a ledger/precompute job —
  tracked in BACKLOG).
- Each task: subagent ship-flow (plan → implement → `/code-review` → fix → local commit). No push.

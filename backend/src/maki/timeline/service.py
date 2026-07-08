import logging
import re
from collections.abc import Callable, Collection
from datetime import UTC, datetime

from maki.aws.ecs_history import ECSDeployHistory
from maki.aws.service_deployments import ECSServiceDeployments
from maki.cache import SwrCache
from maki.github_actions import GitHubActions
from maki.inventory.service import InventoryService
from maki.schemas import DeployTimeline, TimelineSegment

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_PARENS_RE = re.compile(r"\([^)]*\)")
_WS_RE = re.compile(r"\s+")

# Default reusable-workflow suffix parts (the segment after the final " / ") that mark a
# job as a per-service ECS rollout rather than a shared CI stage. Repo-agnostic;
# overridable per TimelineService instance (and via settings).
_DEFAULT_ROLLOUT_SUFFIXES = ("deploy", "schedule")

# Default job-name prefixes that mark a job as a per-service ECS rollout. Overridable
# per instance (and via settings); replaces the old hardcoded 'deploy-' literal.
_DEFAULT_ROLLOUT_PREFIXES = ("deploy-",)

# Max dead-time gap (seconds) between contiguous workflow runs of one deploy. A run that
# starts more than this after the running activity cluster ends is treated as unrelated (e.g.
# the dependency-upgrade workflow that ran on the same sha hours later) and dropped.
_RUN_CLUSTER_GAP_SECONDS = 1800  # 30 minutes

# GitHub Actions job.conclusion -> our segment status vocabulary.
_CONCLUSION_STATUS = {
    "success": "success",
    "failure": "failed",
    "timed_out": "failed",
    "cancelled": "failed",
    "startup_failure": "failed",
    "action_required": "failed",
    "neutral": "success",
    "skipped": "success",
}


def _slug(name: str) -> str:
    return _SLUG_RE.sub("-", name.strip().lower()).strip("-") or "job"


def _is_rollout_job(
    name: str, prefixes: Collection[str], suffixes: Collection[str]
) -> bool:
    """A per-service ECS rollout job that fans out from one CI run (repo-agnostic).

    Excluded from the CI stage: each targets a different sibling service, and
    this service's own rollout is measured accurately from ECS instead.

    A job is a rollout if its name starts with any configured ``prefixes``
    (default {'deploy-'}) — e.g. 'deploy-inventory-service' — OR the
    reusable-workflow suffix part (the segment after the final " / ") is in the
    configured ``suffixes`` (default {deploy, schedule}) — e.g. 'deploy / deploy',
    'schedule-holiday-reset / schedule'. Note 'trigger-deploy' is NOT a rollout:
    it has no ' / deploy' suffix and doesn't start with 'deploy-'.
    """
    lowered = name.strip().lower()
    if any(lowered.startswith(p.lower()) for p in prefixes):
        return True
    suffix = lowered.rsplit(" / ", 1)[-1].strip()
    return suffix in suffixes


def _stage_label(name: str) -> str:
    """Normalize a job name to a wall-clock STAGE label (pure string ops).

    Take the part before the first ' / ' (the reusable caller name), strip ANY
    '(...)' groups anywhere, collapse whitespace, trim. Examples:
    'test (0)'->'Test', 'publish-images (inventory:docker)'->'publish-images',
    'image-tags / image-tags'->'image-tags', 'Test (0) Results'->'Test Results'.
    """
    caller = name.split(" / ", 1)[0]
    no_parens = _PARENS_RE.sub(" ", caller)
    return _WS_RE.sub(" ", no_parens).strip() or "Job"


def _worst_status(statuses: list[str]) -> str:
    if "failed" in statuses:
        return "failed"
    if "in_progress" in statuses:
        return "in_progress"
    if all(s == "success" for s in statuses):
        return "success"
    return "unknown"


def _to_dt(value: object) -> datetime | None:
    """Coerce an ECS datetime or an ISO-8601 string into a datetime; None if absent/invalid."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _seconds(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    return int((end - start).total_seconds())


def _ci_status(conclusion: object) -> str:
    if conclusion is None:
        return "in_progress"  # job still running has no conclusion yet
    if isinstance(conclusion, str):
        return _CONCLUSION_STATUS.get(conclusion, "unknown")
    return "unknown"


class TimelineService:
    """Assemble the full merge -> CI -> rollout -> live timeline for a service's CURRENT deploy.

    Failure-isolated end to end: every external source (inventory snapshot, ECS deployment,
    Actions jobs) degrades to fewer segments rather than an error. SWR-cached per service name.
    """

    def __init__(
        self,
        inventory: InventoryService,
        ecs_client,
        cluster: str,
        service_deployments: ECSServiceDeployments,
        actions: GitHubActions,
        repo_for: Callable[[str], str | None],
        fresh_seconds: float,
        stale_seconds: float,
        rollout_suffixes: tuple[str, ...] | set[str] = _DEFAULT_ROLLOUT_SUFFIXES,
        rollout_prefixes: tuple[str, ...] | set[str] = _DEFAULT_ROLLOUT_PREFIXES,
        group_matrix_jobs: bool = True,
        enabled: bool = True,
    ):
        self._inventory = inventory
        self._ecs = ecs_client
        self._cluster = cluster
        self._service_deployments = service_deployments
        self._actions = actions
        self._repo_for = repo_for
        self._rollout_suffixes = set(rollout_suffixes)
        self._rollout_prefixes = tuple(rollout_prefixes)
        self._group_matrix_jobs = group_matrix_jobs
        self._enabled = enabled
        self._cache = SwrCache(fresh_seconds, stale_seconds)

    def get_timeline(
        self,
        service_name: str,
        sha: str | None = None,
        revision: int | None = None,
        merged_at: datetime | None = None,
        force: bool = False,
    ) -> DeployTimeline:
        """Timeline for a service. No ``sha``/``revision`` → current deploy (unchanged).

        When ``sha`` and/or ``revision`` are given, target THAT past deploy instead: CI from the
        target sha, ECS from the target revision. ``merged_at`` (the target commit's commit
        time, which the caller already holds) anchors the axis and the merge→live total — it
        isn't otherwise recoverable on the targeted path. Cache key includes ``(service_name,
        sha, revision, merged_at)`` so different deploys don't collide.
        """
        key = (service_name, sha, revision, merged_at)
        return self._cache.get(
            key, lambda: self._compute(service_name, sha, revision, merged_at), force=force
        )

    def _compute(
        self,
        service_name: str,
        target_sha: str | None = None,
        target_revision: int | None = None,
        target_merged_at: datetime | None = None,
    ) -> DeployTimeline:
        if not self._enabled:
            # Feature off: no segments, no totals, and no GitHub Actions / ECS lookups.
            return DeployTimeline(
                service=service_name,
                sha=None,
                merged_at=None,
                live_at=None,
                total_seconds=None,
                segments=[],
                run_urls=[],
                generated_at=datetime.now(UTC),
            )

        targeted = target_sha is not None or target_revision is not None

        if targeted:
            sha = target_sha
            merged_at = target_merged_at  # caller-supplied commit time (else axis/total degrade)
            deployed_at = None
        else:
            svc = self._current_service(service_name)
            sha = svc.git_sha if svc else None
            merged_at = svc.committed_at if svc else None
            deployed_at = svc.deployed_at if svc else None

        segments: list[TimelineSegment] = []
        ci_segments, run_urls = self._ci_segments(service_name, sha)
        segments.extend(ci_segments)

        family, current_revision = self._family_and_revision(service_name)
        revision = target_revision if targeted else current_revision
        ecs = (
            self._service_deployments.deployment_for_revision(service_name, revision, family)
            if family and revision is not None
            else None
        )
        segments.extend(self._ecs_segments(ecs))

        _min_utc = datetime.min.replace(tzinfo=UTC)
        segments.sort(
            key=lambda s: (
                s.start is None,
                s.start or _min_utc,
                s.end is None,
                s.end or _min_utc,
                s.key,
            )
        )

        live_at = (ecs or {}).get("finished_at") or deployed_at
        total = _seconds(merged_at, live_at)
        return DeployTimeline(
            service=service_name,
            sha=sha,
            merged_at=merged_at,
            live_at=live_at,
            total_seconds=total,
            segments=segments,
            run_urls=run_urls,
            generated_at=datetime.now(UTC),
        )

    def _current_service(self, service_name: str):
        snapshot = self._inventory.get_inventory()
        for svc in snapshot.services:
            if svc.name == service_name:
                return svc
        return None

    def _deploy_run_jobs(self, jobs: list[dict]) -> list[dict]:
        """Keep only jobs from the workflow runs belonging to THIS deploy's activity cluster.

        ``jobs_for_sha`` returns jobs across EVERY workflow run that touched the sha. A single
        deploy spans several runs that all fire at merge and run contiguously — the CI/test
        run, the build run, the deploy fan-out run, etc. But unrelated runs also touch the same
        commit much later (the ``upgrade-dependencies`` workflow, CodeQL, scheduled jobs); an
        11-minute ``update-dep`` job hours after the deploy was stretching the Gantt axis so
        every real phase squashed to a sliver.

        Filtering to "runs with a rollout job" was too aggressive — the genuine CI runs have no
        rollout job and got dropped. Instead cluster runs by time: order runs by first job
        start, keep the contiguous block starting at the earliest run, and stop at the first
        run separated from the block by more than ``_RUN_CLUSTER_GAP_SECONDS`` of dead time.
        That keeps the whole merge-time pipeline and drops only runs detached far in the
        future. Runs/jobs without timing are always kept (can't reason about them).
        """
        # run_id -> (min_start, max_end) for runs that have any timing.
        spans: dict[object, tuple[datetime, datetime]] = {}
        for job in jobs:
            run_id = job.get("run_id")
            start = _to_dt(job.get("started_at"))
            end = _to_dt(job.get("completed_at"))
            point = start or end
            if run_id is None or point is None:
                continue
            cur = spans.get(run_id)
            lo = point if cur is None else min(cur[0], point)
            hi = (end or point) if cur is None else max(cur[1], end or point)
            spans[run_id] = (lo, hi)

        if len(spans) <= 1:
            return jobs  # nothing to cluster against

        ordered = sorted(spans.items(), key=lambda kv: kv[1][0])
        kept_runs: set[object] = {ordered[0][0]}
        cluster_end = ordered[0][1][1]
        for run_id, (lo, hi) in ordered[1:]:
            if (lo - cluster_end).total_seconds() > _RUN_CLUSTER_GAP_SECONDS:
                break  # detached run (and everything after it) — unrelated to this deploy
            kept_runs.add(run_id)
            cluster_end = max(cluster_end, hi)

        # Keep clustered runs + any job whose run has no timing to cluster on.
        return [
            job
            for job in jobs
            if job.get("run_id") in kept_runs or job.get("run_id") not in spans
        ]

    def _run_urls(self, jobs: list[dict]) -> list[str]:
        """Distinct GitHub Actions run URLs behind ``jobs``, first-seen order.

        ``jobs`` is expected to already be filtered by ``_deploy_run_jobs`` so a
        cluster-dropped run's URL never leaks into the result.
        """
        seen: set[object] = set()
        urls: list[str] = []
        for job in jobs:
            run_id = job.get("run_id")
            url = job.get("html_url")
            if run_id is None or run_id in seen or not url:
                continue
            seen.add(run_id)
            urls.append(url)
        return urls

    def _ci_segments(
        self, service_name: str, sha: str | None
    ) -> tuple[list[TimelineSegment], list[str]]:
        """Collapse GH-Actions jobs into wall-clock CI phases (repo-agnostic).

        A monorepo CI run fans out: parallel matrix jobs (`test (0..3)`), one
        `image-tags / image-tags` per project, per-service rollout jobs, etc.
        Summing per-job durations is meaningless. Instead: drop rollout jobs,
        normalize each remaining job's name to a STAGE label, GROUP by that
        label, and emit ONE phase per group whose span is the wall-clock
        min(start)..max(end) across the group — so overlapping parallel jobs
        collapse to their true elapsed time, not their sum. Also returns the
        run URLs behind the surviving jobs (see ``_run_urls``).
        """
        if not sha:
            return [], []
        repo = self._repo_for(service_name)
        if repo is None:
            return [], []
        jobs = self._actions.jobs_for_sha(repo, sha)
        jobs = self._deploy_run_jobs(jobs)
        run_urls = self._run_urls(jobs)

        # key -> aggregated phase state, preserving first-seen order.
        groups: dict[str, dict] = {}
        for job in jobs:
            name = job.get("name") or "Job"
            if _is_rollout_job(name, self._rollout_prefixes, self._rollout_suffixes):
                continue
            # Grouping on: collapse matrix shards to a STAGE label (parens stripped).
            # Grouping off: each distinct raw job name is its own segment.
            label = _stage_label(name) if self._group_matrix_jobs else name
            key = _slug(label)
            start = _to_dt(job.get("started_at"))
            end = _to_dt(job.get("completed_at"))
            status = _ci_status(job.get("conclusion"))
            group = groups.get(key)
            if group is None:
                groups[key] = {
                    "label": label,
                    "start": start,
                    "end": end,
                    "statuses": [status],
                    "count": 1,
                }
                continue
            group["count"] += 1
            group["statuses"].append(status)
            if start is not None and (group["start"] is None or start < group["start"]):
                group["start"] = start
            if end is not None and (group["end"] is None or end > group["end"]):
                group["end"] = end

        segments: list[TimelineSegment] = []
        for key, group in groups.items():
            start = group["start"]
            end = group["end"]
            segments.append(
                TimelineSegment(
                    key=f"ci:{key}",
                    label=group["label"],
                    source="github_actions",
                    start=start,
                    end=end,
                    seconds=_seconds(start, end),
                    status=_worst_status(group["statuses"]),
                    count=group["count"],
                )
            )
        return segments, run_urls

    def _ecs_segments(self, ecs: dict | None) -> list[TimelineSegment]:
        if not ecs:
            return []
        created = _to_dt(ecs.get("created_at"))
        started = _to_dt(ecs.get("started_at"))
        finished = _to_dt(ecs.get("finished_at"))
        status = _ecs_status(ecs.get("status"))
        segments: list[TimelineSegment] = []
        if created is not None or started is not None:
            segments.append(
                TimelineSegment(
                    key="ecs:queued",
                    label="Queued",
                    source="ecs",
                    start=created,
                    end=started,
                    seconds=_seconds(created, started),
                    status=status,
                )
            )
        if started is not None or finished is not None:
            segments.append(
                TimelineSegment(
                    key="ecs:rollout",
                    label="Rollout",
                    source="ecs",
                    start=started,
                    end=finished,
                    seconds=_seconds(started, finished),
                    status=status,
                )
            )
        return segments

    def _family_and_revision(self, service_name: str) -> tuple[str | None, int | None]:
        """Resolve the family + task-def revision of the service's CURRENT primary deployment."""
        try:
            resp = self._ecs.describe_services(cluster=self._cluster, services=[service_name])
        except Exception:  # noqa: BLE001 - ECS segments are optional, never break the timeline
            logger.warning("describe_services failed for %r", service_name, exc_info=True)
            return None, None
        services = resp.get("services", [])
        if not services:
            return None, None
        arn = services[0].get("taskDefinition")
        if not arn:
            return None, None
        return ECSDeployHistory.family_from_arn(arn), ECSDeployHistory._revision_from_arn(arn)


def _ecs_status(state: object) -> str:
    if not isinstance(state, str):
        return "unknown"
    if state in ("SUCCESSFUL", "ROLLBACK_SUCCESSFUL"):
        return "success"
    if state in ("IN_PROGRESS", "PENDING"):
        return "in_progress"
    if state in ("STOPPED", "ROLLBACK_FAILED", "ROLLBACK_IN_PROGRESS"):
        return "failed"
    return "unknown"

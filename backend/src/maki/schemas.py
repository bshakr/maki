from datetime import datetime

from pydantic import BaseModel


class DeployedService(BaseModel):
    name: str
    platform: str  # "ecs" | "amplify"
    env: str = "production"
    git_sha: str | None = None
    image: str | None = None
    deployed_at: datetime | None = None
    running_count: int | None = None
    desired_count: int | None = None
    pending_count: int | None = None
    status: str | None = None
    version: str | None = None  # full deployed image tag (part after the last ":")
    region: str | None = None  # AWS region (ECS only; static across services)
    rollout_progress: float | None = None  # percent 0..100 of the primary deployment
    rollout_reason: str | None = None  # primary deployment's rolloutStateReason
    cpu_reservation: int | None = None  # container CPU reservation from the task def
    mem_reservation: int | None = None  # container memory reservation from the task def
    commit_url: str | None = None
    author: str | None = None
    author_avatar_url: str | None = None
    message: str | None = None
    pr_url: str | None = None
    committed_at: datetime | None = None


class ServicesResponse(BaseModel):
    services: list[DeployedService]
    generated_at: datetime


class CommitInfo(BaseModel):
    author: str | None = None
    author_avatar_url: str | None = None
    message: str | None = None
    commit_url: str | None = None
    pr_url: str | None = None
    committed_at: datetime | None = None


class DeployRecord(BaseModel):
    # deploy_events row id — stable React key, survives appended pages + redeploys. Populated by
    # the store-backed history reads; None for in-memory records the ingester builds pre-persist.
    id: int | None = None
    sha: str | None = None
    image: str | None = None
    revision: int | None = None
    registered_at: datetime | None = None
    author: str | None = None  # filled by GitHub enrich (later task)
    author_avatar_url: str | None = None
    message: str | None = None
    commit_url: str | None = None
    pr_url: str | None = None
    committed_at: datetime | None = None
    finished_at: datetime | None = None  # rollout fully live in prod (ECS service deployment)
    status: str | None = None  # normalized rollout state: in_progress | success | failed | None
    is_rollback: bool = False  # True when the rollout was an ECS rollback, not a forward deploy


class DeploymentsResponse(BaseModel):
    service: str
    deployments: list[DeployRecord]
    generated_at: datetime
    # Opaque keyset cursor for the next (older) page of this service's history; None when there are
    # no more rows. Mirrors ActivityResponse.next_cursor.
    next_cursor: str | None = None


class ActivityItem(BaseModel):
    id: int  # deploy_events row id — stable React key, survives appended pages + redeploys
    service: str
    platform: str
    sha: str | None = None
    deployed_at: datetime | None = None
    status: str | None = None  # in_progress | success | failed | None
    is_rollback: bool = False
    author: str | None = None
    author_avatar_url: str | None = None
    message: str | None = None
    commit_url: str | None = None
    pr_url: str | None = None
    committed_at: datetime | None = None


class ActivityResponse(BaseModel):
    items: list[ActivityItem]
    generated_at: datetime
    # Opaque keyset cursor for the next (older) page of the default feed; ``None`` when there are
    # no more pages or for the bounded "jump to timestamp" path (which is not paginated).
    next_cursor: str | None = None


class DeployCountResponse(BaseModel):
    count: int
    since: datetime
    generated_at: datetime


class MetricBucket(BaseModel):
    date: str  # YYYY-MM-DD (UTC)
    count: int


class LeadTimeBucket(BaseModel):
    date: str  # YYYY-MM-DD (UTC)
    median_seconds: int | None = None  # total lead time (committed → live)
    ci_median_seconds: int | None = None  # committed → registered
    rollout_median_seconds: int | None = None  # registered → live


class DeployLeadEntry(BaseModel):
    """One deploy ranked by lead time (committed → live) for the slowest/fastest leaderboards."""

    service: str
    sha: str | None = None
    author: str | None = None
    lead_seconds: int  # committed → live, via the shared lead-time rule
    deployed_at: datetime | None = None  # finished_at (go-live)


class MetricsDelta(BaseModel):
    """The four DORA headline metrics over the PREVIOUS equal-length window [2×range, range).

    Lets the frontend show ↑/↓ deltas vs the prior period. Each field mirrors the headline of the
    same name; None where the previous window had no qualifying data (same nullability as current).
    """

    deploys_per_day: float
    lead_time_median_seconds: int | None = None
    change_fail_rate: float
    mttr_median_seconds: int | None = None


class MetricsResponse(BaseModel):
    range_days: int
    service: str
    deploy_count: int
    deploys_per_day: float
    lead_time_median_seconds: int | None = None  # committed → live (merge to fully-in-prod)
    lead_time_p90_seconds: int | None = None  # committed → live, 90th percentile
    ci_median_seconds: int | None = None  # committed → registered (CI/build)
    rollout_median_seconds: int | None = None  # registered → live (ECS rollout)
    last_deployed_at: datetime | None = None  # max finished_at, falling back to registered_at
    # Change-fail: failed rollouts + rollbacks, each event counted once even if both.
    failed_count: int = 0
    rollback_count: int = 0
    change_fail_rate: float = 0.0  # 0..1 fraction; guard /0 -> 0.0
    fail_trend: list[MetricBucket] = []  # per-day failed+rollback count (fail markers / sparkline)
    # MTTR: median recovery time (failed/rollback go-live → next same-service success go-live).
    # None when no recovered incident in the window. Unrecovered incidents are excluded.
    mttr_median_seconds: int | None = None
    # Same four headline metrics over the previous equal-length window, for period-over-period ↑/↓.
    previous: MetricsDelta | None = None
    # Top-5 longest / shortest lead-time deploys within the window (valid lead time only).
    slowest_deploys: list[DeployLeadEntry] = []
    fastest_deploys: list[DeployLeadEntry] = []
    trend: list[MetricBucket]
    lead_time_trend: list[LeadTimeBucket] = []  # per-day median committed → live
    services: list[str]
    generated_at: datetime


class TaskHistoryPoint(BaseModel):
    timestamp: datetime
    running: int | None = None
    desired: int | None = None


class TaskHistoryResponse(BaseModel):
    service: str
    range_days: int
    period_seconds: int
    points: list[TaskHistoryPoint]
    generated_at: datetime


class LogEventItem(BaseModel):
    timestamp: datetime
    message: str
    stream: str


class ServiceLogsResponse(BaseModel):
    log_group: str  # resolved log group (task def awslogs-group, else /ecs/<service>-production)
    region: str
    events: list[LogEventItem]
    truncated: bool = False  # True when older events exist beyond the returned slice
    # None on success; "not_found" when the log group is absent; "forbidden" when maki's role
    # lacks logs:FilterLogEvents. The SPA renders a fallback (console link) for the non-null cases.
    error: str | None = None


class TimelineSegment(BaseModel):
    key: str  # e.g. "ci:build", "ecs:queued", "ecs:rollout"
    label: str
    source: str  # "github_actions" | "ecs"
    start: datetime | None = None
    end: datetime | None = None
    seconds: int | None = None
    status: str = "unknown"  # success | failed | in_progress | unknown
    count: int = 1  # number of underlying GH-Actions jobs collapsed into this phase


class DeployTimeline(BaseModel):
    service: str
    sha: str | None = None
    merged_at: datetime | None = None
    live_at: datetime | None = None
    total_seconds: int | None = None
    segments: list[TimelineSegment]
    run_urls: list[str] = []  # GitHub Actions run page(s) behind the CI segments, run order
    generated_at: datetime


class PullDescription(BaseModel):
    number: int
    title: str | None = None
    body_excerpt: str | None = None
    url: str | None = None


class EnvVar(BaseModel):
    name: str
    value: str | None = None  # ECS allows an env entry with no value; don't 500 the env tab


class SecretRef(BaseModel):
    name: str
    value_from: str  # an SSM/Secrets-Manager ARN reference — never the secret value


class ContainerEnv(BaseModel):
    name: str
    environment: list[EnvVar]
    secrets: list[SecretRef]


class ServiceEnvResponse(BaseModel):
    service: str
    task_def: str | None = None
    containers: list[ContainerEnv]
    generated_at: datetime


class RolloutDeployment(BaseModel):
    status: str  # "PRIMARY" | "ACTIVE"
    # IN_PROGRESS | COMPLETED | FAILED (PRIMARY only, None for ACTIVE/untracked)
    rollout_state: str | None
    rollout_reason: str | None
    desired_count: int | None
    running_count: int | None
    pending_count: int | None
    failed_tasks: int | None
    task_definition: str | None  # full task-def ARN (revision readable from its suffix)
    created_at: datetime | None
    updated_at: datetime | None


class RolloutStatusResponse(BaseModel):
    service: str
    deployments: list[RolloutDeployment]  # PRIMARY first, then ACTIVE (draining), newest first
    # PRIMARY rollout_state == "IN_PROGRESS" or any ACTIVE deployment still has tasks
    in_progress: bool
    generated_at: datetime


class RollbackPreview(BaseModel):
    service: str
    target_sha: str
    executed: bool = False
    message: str


class RunTaskPreview(BaseModel):
    service: str
    command: str
    task_def: str | None = None
    executed: bool = False
    message: str


class ThemeView(BaseModel):
    # shadcn token -> value, split by mode. Empty maps when the theme block sets only one mode.
    light: dict[str, str] = {}
    dark: dict[str, str] = {}


class GroupingRuleView(BaseModel):
    match: str
    label: str
    exact: bool = False


class UiConfigResponse(BaseModel):
    """The deployment-specific config the SPA needs at boot. UI-relevant subset only — no repo map,
    no secrets. Served by GET /api/config so one image can serve any tenant without a rebuild."""

    app_name: str
    theme: ThemeView | None = None
    env_label: str
    aws_region: str
    log_group_template: str
    amplify_enabled: bool
    grouping_rules: list[GroupingRuleView] = []
    deploy_timeline_enabled: bool
    auth_required: bool = False


class IdentityResponse(BaseModel):
    """The assumed AWS caller identity behind the running backend.

    Fields are nullable so the UI degrades gracefully: when creds are present they carry the STS
    account id and a friendly name parsed out of the assumed-role ARN; the creds-unavailable path
    is handled separately (503) by the shared AWS error handler.
    """

    account: str | None = None  # 12-digit AWS account id
    arn: str | None = None  # full caller ARN from sts:GetCallerIdentity
    user_id: str | None = None  # STS UserId
    name: str | None = None  # friendly role/session name parsed from the ARN
    region: str | None = None

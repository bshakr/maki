import { clearAuthToken, getAuthToken } from "@/lib/auth-token";

// Typed code the backend returns (HTTP 503) when AWS creds are missing/expired.
// Keep in sync with backend/src/maki/aws/errors.py::CREDENTIALS_UNAVAILABLE.
export const AWS_CREDENTIALS_UNAVAILABLE = "aws_credentials_unavailable";

/** Thrown by every fetcher when the backend reports missing/expired AWS creds (503). */
export class AwsCredentialsError extends Error {
  readonly code = AWS_CREDENTIALS_UNAVAILABLE;
  constructor(message?: string) {
    super(
      message ??
        "AWS credentials are missing or expired. Re-run `assume` and restart the backend.",
    );
    this.name = "AwsCredentialsError";
  }
}

export function isAwsCredentialsError(err: unknown): err is AwsCredentialsError {
  return err instanceof AwsCredentialsError;
}

/** Shared response guard: raises AwsCredentialsError on the typed 503, else a generic Error. */
async function ensureOk(r: Response, what: string): Promise<Response> {
  if (r.ok) return r;
  if (r.status === 503) {
    const body = await r.json().catch(() => null);
    if (body?.error === AWS_CREDENTIALS_UNAVAILABLE) {
      throw new AwsCredentialsError(body.detail);
    }
  }
  throw new Error(`Failed to ${what}: ${r.status}`);
}

/**
 * fetch wrapper for the maki API: attaches the bearer token when set, and on a 401 clears the
 * stored token and fires `maki:unauthorized` so the auth gate can re-prompt. All /api calls go
 * through this so auth is uniform.
 */
export async function apiFetch(input: string, init?: RequestInit): Promise<Response> {
  const token = getAuthToken();
  const headers = new Headers(init?.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const r = await fetch(input, { ...init, headers });
  if (r.status === 401) {
    clearAuthToken();
    window.dispatchEvent(new CustomEvent("maki:unauthorized"));
  }
  return r;
}

export interface DeployedService {
  name: string;
  platform: "ecs" | "amplify";
  env: string;
  git_sha: string | null;
  image: string | null;
  deployed_at: string | null;
  running_count: number | null;
  desired_count: number | null;
  pending_count: number | null;
  status: string | null;
  commit_url: string | null;
  author: string | null;
  author_avatar_url: string | null;
  message: string | null;
  pr_url: string | null;
  committed_at: string | null;
  // Live ECS enrichments (null for Amplify / when unavailable). Optional so the
  // throwaway /proto mocks still satisfy the type until they're removed.
  version?: string | null;
  region?: string | null;
  rollout_progress?: number | null;
  rollout_reason?: string | null;
  cpu_reservation?: number | null;
  mem_reservation?: number | null;
}

export interface ServicesResponse {
  services: DeployedService[];
  generated_at: string;
}

export async function fetchServices(opts?: {
  refresh?: boolean;
}): Promise<ServicesResponse> {
  const r = await apiFetch(`/api/services${opts?.refresh ? "?refresh=1" : ""}`);
  return (await ensureOk(r, "load services")).json();
}

export interface IdentityResponse {
  account: string | null;
  arn: string | null;
  user_id: string | null;
  name: string | null;
  region: string | null;
}

export async function fetchIdentity(): Promise<IdentityResponse> {
  const r = await apiFetch("/api/identity");
  return (await ensureOk(r, "load identity")).json();
}

export interface GroupingRule {
  match: string;
  label: string;
  exact: boolean;
}

// Deployment-specific config the SPA reads once at boot (GET /api/config). UI-relevant subset only.
export interface AppConfigResponse {
  app_name: string;
  theme: { light: Record<string, string>; dark: Record<string, string> } | null;
  env_label: string;
  aws_region: string;
  log_group_template: string;
  amplify_enabled: boolean;
  grouping_rules: GroupingRule[];
  deploy_timeline_enabled: boolean;
  auth_required: boolean;
}

export async function fetchAppConfig(): Promise<AppConfigResponse> {
  const r = await apiFetch("/api/config");
  return (await ensureOk(r, "load config")).json();
}

export interface DeployRecord {
  /** deploy_events row id — stable React key. Null for synthesized/live records with no DB row. */
  id: number | null;
  sha: string | null;
  image: string | null;
  revision: number | null;
  registered_at: string | null;
  author: string | null;
  author_avatar_url: string | null;
  message: string | null;
  commit_url: string | null;
  pr_url: string | null;
  committed_at: string | null;
  finished_at: string | null;
  /** Normalized ECS rollout outcome (null when older than ECS retention). */
  status: "in_progress" | "success" | "failed" | null;
  /** True when this deploy rolled back to an earlier revision. */
  is_rollback: boolean;
}

export interface DeploymentsResponse {
  service: string;
  deployments: DeployRecord[];
  generated_at: string;
  /** Opaque keyset cursor for the next (older) page; null when there are no more. */
  next_cursor: string | null;
}

// Fetch a page of one service's deploy history (newest first). Pass `cursor` (from a previous
// response's `next_cursor`) to load the next, older page. `refresh` bypasses the server cache for
// page 1.
export async function fetchDeployments(
  name: string,
  opts?: { refresh?: boolean; cursor?: string },
): Promise<DeploymentsResponse> {
  const p = new URLSearchParams();
  if (opts?.refresh) p.set("refresh", "1");
  if (opts?.cursor) p.set("cursor", opts.cursor);
  const qs = p.toString();
  const r = await apiFetch(
    `/api/services/${encodeURIComponent(name)}/deployments${qs ? `?${qs}` : ""}`,
  );
  return (await ensureOk(r, "load deployments")).json();
}

// Fetch a single deploy by short-sha prefix (the URL carries a 7-char sha; the store has the full
// sha, matched on prefix). Backs the deploy-sheet deep link for shas not in the loaded history page.
// Returns null when no deploy matches (404) so the caller can leave the sheet closed; other failures
// throw (incl. the AWS-credentials sentinel via `ensureOk`).
export async function fetchDeploy(
  name: string,
  sha: string,
): Promise<DeployRecord | null> {
  const r = await apiFetch(
    `/api/services/${encodeURIComponent(name)}/deploys/${encodeURIComponent(sha)}`,
  );
  if (r.status === 404) return null;
  return (await ensureOk(r, "load deploy")).json();
}

export interface ActivityItem {
  /** deploy_events row id — stable React key, survives appended pages + same-(service,sha) redeploys. */
  id: number;
  service: string;
  platform: "ecs" | "amplify";
  sha: string | null;
  deployed_at: string | null;
  /** Normalized ECS rollout outcome (null when older than ECS retention). */
  status: "in_progress" | "success" | "failed" | null;
  /** True when this deploy rolled back to an earlier revision. */
  is_rollback: boolean;
  author: string | null;
  author_avatar_url: string | null;
  message: string | null;
  commit_url: string | null;
  pr_url: string | null;
  committed_at: string | null;
}

export interface ActivityResponse {
  items: ActivityItem[];
  generated_at: string;
  /** Opaque keyset cursor for the next (older) page; null when there are no more. */
  next_cursor: string | null;
}

// Fetch a page of the default (latest-first) feed. Pass `cursor` (from a previous response's
// `next_cursor`) to load the next, older page. `refresh` bypasses the server cache for page 1.
export async function fetchActivity(opts?: {
  refresh?: boolean;
  cursor?: string;
}): Promise<ActivityResponse> {
  const p = new URLSearchParams();
  if (opts?.refresh) p.set("refresh", "1");
  if (opts?.cursor) p.set("cursor", opts.cursor);
  const qs = p.toString();
  const r = await apiFetch(`/api/activity${qs ? `?${qs}` : ""}`);
  return (await ensureOk(r, "load activity")).json();
}

export interface DeployCountResponse {
  count: number;
  since: string;
  generated_at: string;
}

// Fleet-wide count of ECS deploy events registered at/after `sinceIso` (an ISO-8601 instant).
export async function fetchDeployCount(sinceIso: string): Promise<DeployCountResponse> {
  const r = await apiFetch(`/api/activity/deploy-count?since=${encodeURIComponent(sinceIso)}`);
  return (await ensureOk(r, "load deploy count")).json();
}

// Fetch the deploy feed centred on a target moment (incident triage): every event whose
// go-live time falls within ±`windowHours` of `around`. `around` is an ISO-8601 timestamp.
export async function fetchActivityAround(
  around: string,
  windowHours: number,
): Promise<ActivityResponse> {
  const p = new URLSearchParams({ around, window: String(windowHours) });
  const r = await apiFetch(`/api/activity?${p.toString()}`);
  return (await ensureOk(r, "load activity")).json();
}

export interface RollbackPreview {
  service: string;
  target_sha: string;
  executed: boolean;
  message: string;
}

export async function previewRollback(
  name: string,
  targetSha: string,
): Promise<RollbackPreview> {
  const r = await apiFetch(`/api/services/${encodeURIComponent(name)}/rollback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target_sha: targetSha }),
  });
  return (await ensureOk(r, "preview rollback")).json();
}

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
  const r = await apiFetch(`/api/services/${encodeURIComponent(name)}/run-task`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command, task_def: taskDef }),
  });
  return (await ensureOk(r, "preview run-task")).json();
}

export interface TimelineSegment {
  key: string;
  label: string;
  source: "github_actions" | "ecs";
  start: string | null;
  end: string | null;
  seconds: number | null;
  status: "success" | "failed" | "in_progress" | "unknown";
  count: number;
}

export interface DeployTimeline {
  service: string;
  sha: string | null;
  merged_at: string | null;
  live_at: string | null;
  total_seconds: number | null;
  segments: TimelineSegment[];
  run_urls?: string[];
  generated_at: string;
}

export async function fetchDeployTimeline(
  name: string,
  opts?: { sha?: string; revision?: number; mergedAt?: string; refresh?: boolean },
): Promise<DeployTimeline> {
  const p = new URLSearchParams();
  if (opts?.sha) p.set("sha", opts.sha);
  if (opts?.revision != null) p.set("revision", String(opts.revision));
  if (opts?.mergedAt) p.set("merged_at", opts.mergedAt);
  if (opts?.refresh) p.set("refresh", "1");
  const qs = p.toString();
  const r = await apiFetch(
    `/api/services/${encodeURIComponent(name)}/deploy-timeline${
      qs ? `?${qs}` : ""
    }`,
  );
  return (await ensureOk(r, "load deploy timeline")).json();
}

export interface PullDescription {
  number: number;
  title: string | null;
  body_excerpt: string | null;
  // null when the service has no configured repo (enrichment skipped) — backend returns null then.
  url: string | null;
}

export async function fetchPullDescription(
  name: string,
  number: number,
): Promise<PullDescription> {
  const r = await apiFetch(
    `/api/services/${encodeURIComponent(name)}/pull?number=${number}`,
  );
  return (await ensureOk(r, "load PR description")).json();
}

export interface MetricBucket {
  date: string;
  count: number;
}

export interface LeadTimeBucket {
  date: string;
  median_seconds: number | null;
  ci_median_seconds: number | null;
  rollout_median_seconds: number | null;
}

export interface DeployLeadEntry {
  service: string;
  sha: string | null;
  author: string | null;
  /** committed → live lead time, in seconds. */
  lead_seconds: number;
  deployed_at: string | null;
}

/** The four DORA headline metrics over the previous equal-length window, for ↑/↓ deltas. */
export interface MetricsDelta {
  deploys_per_day: number;
  lead_time_median_seconds: number | null;
  change_fail_rate: number;
  mttr_median_seconds: number | null;
}

export interface MetricsResponse {
  range_days: number;
  service: string;
  deploy_count: number;
  deploys_per_day: number;
  lead_time_median_seconds: number | null;
  lead_time_p90_seconds: number | null;
  ci_median_seconds: number | null;
  rollout_median_seconds: number | null;
  last_deployed_at: string | null;
  /** Failed rollouts in the window. */
  failed_count: number;
  /** Rollback deploys in the window. */
  rollback_count: number;
  /** failures (failed rollout OR rollback, counted once) / deploy_count, as a 0..1 fraction. */
  change_fail_rate: number;
  /** Per-day failed+rollback count, aligned to `trend` for fail markers. */
  fail_trend: MetricBucket[];
  /** Median recovery time (failure → next same-service success); null if no recovery. */
  mttr_median_seconds: number | null;
  /** Same four headline metrics over the previous equal-length window. */
  previous: MetricsDelta | null;
  /** Top-5 longest-lead-time deploys in the window. */
  slowest_deploys: DeployLeadEntry[];
  /** Top-5 shortest-lead-time deploys in the window. */
  fastest_deploys: DeployLeadEntry[];
  trend: MetricBucket[];
  lead_time_trend: LeadTimeBucket[];
  services: string[];
  generated_at: string;
}

export async function fetchMetrics(opts?: {
  rangeDays?: number;
  service?: string;
  refresh?: boolean;
}): Promise<MetricsResponse> {
  const p = new URLSearchParams();
  if (opts?.rangeDays) p.set("range_days", String(opts.rangeDays));
  if (opts?.service) p.set("service", opts.service);
  if (opts?.refresh) p.set("refresh", "1");
  const qs = p.toString();
  const r = await apiFetch(`/api/metrics${qs ? `?${qs}` : ""}`);
  return (await ensureOk(r, "load metrics")).json();
}

export interface TaskHistoryPoint {
  timestamp: string;
  running: number | null;
  desired: number | null;
}

export interface TaskHistoryResponse {
  service: string;
  range_days: number;
  period_seconds: number;
  points: TaskHistoryPoint[];
  generated_at: string;
}

export async function fetchTaskHistory(
  name: string,
  opts?: { rangeDays?: number; refresh?: boolean },
): Promise<TaskHistoryResponse> {
  const p = new URLSearchParams();
  if (opts?.rangeDays) p.set("range_days", String(opts.rangeDays));
  if (opts?.refresh) p.set("refresh", "1");
  const qs = p.toString();
  const r = await apiFetch(
    `/api/services/${encodeURIComponent(name)}/task-history${qs ? `?${qs}` : ""}`,
  );
  return (await ensureOk(r, "load task history")).json();
}

export interface EnvVar {
  name: string;
  value: string;
}

export interface SecretRef {
  name: string;
  value_from: string;
}

export interface ContainerEnv {
  name: string;
  environment: EnvVar[];
  secrets: SecretRef[];
}

export interface ServiceEnvResponse {
  service: string;
  task_def: string | null;
  containers: ContainerEnv[];
  generated_at: string;
}

export async function fetchServiceEnv(
  name: string,
  opts?: { refresh?: boolean },
): Promise<ServiceEnvResponse> {
  const r = await apiFetch(
    `/api/services/${encodeURIComponent(name)}/env${opts?.refresh ? "?refresh=1" : ""}`,
  );
  return (await ensureOk(r, "load env")).json();
}

export interface RolloutDeployment {
  status: string; // "PRIMARY" | "ACTIVE"
  rollout_state: string | null; // IN_PROGRESS | COMPLETED | FAILED (PRIMARY only)
  rollout_reason: string | null;
  desired_count: number | null;
  running_count: number | null;
  pending_count: number | null;
  failed_tasks: number | null;
  task_definition: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface RolloutStatusResponse {
  service: string;
  deployments: RolloutDeployment[];
  in_progress: boolean;
  generated_at: string;
}

// Live rollout view for one ECS service, meant to be polled while a rollout is in progress.
// Deliberately not cached server-side, so callers should gate polling on `in_progress`.
export async function fetchRollout(name: string): Promise<RolloutStatusResponse> {
  const r = await apiFetch(`/api/services/${encodeURIComponent(name)}/rollout`);
  return (await ensureOk(r, "load rollout")).json();
}

export interface LogEventItem {
  timestamp: string;
  message: string;
  stream: string;
}

/** Typed soft-failures the log tail can report (HTTP 200, not an error). */
export type ServiceLogsError = "not_found" | "forbidden";

export interface ServiceLogsResponse {
  log_group: string;
  region: string;
  events: LogEventItem[];
  /** True when older events exist beyond the returned slice. */
  truncated: boolean;
  /** null on success; "not_found" when the group is absent; "forbidden" when the role can't read it. */
  error: ServiceLogsError | null;
}

// Fetch a tail of a service's CloudWatch logs (resolved as /ecs/<name>-production). A 503 raises
// AwsCredentialsError (missing/expired creds → re-assume affordance); the not_found / forbidden
// states come back as a 200 with a typed `error` so the UI can show a fallback console link.
export async function fetchServiceLogs(
  name: string,
  opts?: { limit?: number; sinceMinutes?: number; refresh?: boolean },
): Promise<ServiceLogsResponse> {
  const p = new URLSearchParams();
  if (opts?.limit != null) p.set("limit", String(opts.limit));
  if (opts?.sinceMinutes != null) p.set("since_minutes", String(opts.sinceMinutes));
  if (opts?.refresh) p.set("refresh", "1");
  const qs = p.toString();
  const r = await apiFetch(
    `/api/services/${encodeURIComponent(name)}/logs${qs ? `?${qs}` : ""}`,
  );
  return (await ensureOk(r, "load logs")).json();
}

export interface VersionResponse {
  current_sha: string | null;
  /** Upstream ref compared against, e.g. "origin/main". Null when the check couldn't run. */
  upstream: string | null;
  /** Commits behind the upstream tip; null when unknown (remote object never fetched). */
  behind_by: number | null;
  update_available: boolean;
}

// Clone freshness (is this checkout behind its upstream?). The backend caches the git
// check and re-runs it hourly, so polling this is cheap.
export async function fetchVersion(): Promise<VersionResponse> {
  const r = await apiFetch("/api/version");
  return (await ensureOk(r, "load version")).json();
}

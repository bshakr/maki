import type { DeployedService } from "@/api";

export type Health = "healthy" | "deploying" | "error";

// Amplify job statuses that mean a deploy is mid-flight (ECS only ever
// reports IN_PROGRESS).
const DEPLOYING_STATUSES = new Set([
  "IN_PROGRESS",
  "PENDING",
  "PROVISIONING",
  "RUNNING",
  "CANCELLING",
]);

export function healthOf(svc: DeployedService): Health {
  const status = svc.status;
  // Explicit failure / unavailable states are degraded regardless of counts.
  // CANCELLED (Amplify) also counts: the app is stuck on an unintended version.
  const errorish =
    status != null &&
    (status === "FAILED" ||
      status === "CANCELLED" ||
      status.toLowerCase().includes("unavailable") ||
      status.toLowerCase().includes("error"));
  if (errorish) return "error";
  // Actively rolling out. ECS only reports rolloutState=IN_PROGRESS for services
  // configured with rollout tracking (circuit breaker); others report null while
  // a deploy is mid-flight. So pending tasks (being launched) ALSO mean
  // "deploying", not degraded — a fresh deploy at 0/2 with pending tasks is
  // ramping up, not broken. (A null status is NOT treated as an error.)
  if (status != null && DEPLOYING_STATUSES.has(status)) return "deploying";
  if (svc.pending_count != null && svc.pending_count > 0) return "deploying";
  // Settled (no rollout, no tasks launching) but missing tasks → genuinely
  // degraded: the deploy isn't progressing yet can't hold its desired count.
  const understaffed =
    svc.running_count != null &&
    svc.desired_count != null &&
    svc.running_count < svc.desired_count;
  if (understaffed) return "error";
  return "healthy";
}

// Stable, severity-first ordering so broken services sort to the front.
export const HEALTH_RANK: Record<Health, number> = {
  error: 0,
  deploying: 1,
  healthy: 2,
};

// Calm-by-default presentation. Saturated color (left border) is reserved for
// problems; healthy gets no colored border. The single always-present status
// signal is a small top-right dot: muted/green for healthy, colored otherwise.
export const HEALTH_PRESENTATION: Record<
  Health,
  {
    // Display word for the card (raw ECS status stays on the detail page).
    word: string;
    // Colored left border — only set for problems.
    border: string;
    // Status dot color.
    dot: string;
  }
> = {
  healthy: {
    word: "stable",
    border: "",
    dot: "bg-green-500/60",
  },
  deploying: {
    word: "deploying",
    border: "border-l-amber-500",
    dot: "bg-amber-500",
  },
  error: {
    word: "degraded",
    border: "border-l-red-500",
    dot: "bg-red-500",
  },
};

export function healthWord(health: Health): string {
  return HEALTH_PRESENTATION[health].word;
}

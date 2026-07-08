export function shortSha(sha: string | null): string {
  return sha ? sha.slice(0, 7) : "—";
}

// Format a Date as the local "YYYY-MM-DDTHH:mm" string a native datetime-local input speaks, so
// callers stay timezone-naive (local). Shared by the activity jump control and the date-time picker.
export function toLocalInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}`;
}

// Collapse a long ECR image URI to the human-readable repo + short tag, e.g.
// "527…amazonaws.com/nlabour:cf930b6819ffc…" → "nlabour:cf930b6". Takes the
// path segment after the last "/", and if the tag looks like a long sha
// (hex, ≥8 chars) shortens it to 7 chars.
export function compactImage(image: string | null): string {
  if (!image) return "—";
  const last = image.slice(image.lastIndexOf("/") + 1);
  const colon = last.lastIndexOf(":");
  if (colon === -1) return last;
  const repo = last.slice(0, colon);
  const tag = last.slice(colon + 1);
  const isLongSha = /^[0-9a-f]{8,}$/i.test(tag);
  return `${repo}:${isLongSha ? tag.slice(0, 7) : tag}`;
}

export function ago(iso: string | null): string {
  if (!iso) return "—";
  const s = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

// Absolute local timestamp for investigation, e.g. "Jun 4, 2026, 14:30" — the
// exact moment a deploy went live, so it correlates directly with dashboards
// and alerts. 24-hour clock to avoid AM/PM ambiguity.
export function timestamp(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

// Same moment, second precision — for hover titles where exact ordering matters.
export function timestampPrecise(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "medium",
  });
}

// Lead time in seconds from when a PR was merged (approximated by the commit's
// committer timestamp) to when it went live. Returns null unless both ISO
// timestamps parse and live >= merged (guards clock skew / bad data).
export function leadTimeSeconds(
  mergedIso: string | null,
  liveIso: string | null,
): number | null {
  if (!mergedIso || !liveIso) return null;
  const merged = new Date(mergedIso).getTime();
  const live = new Date(liveIso).getTime();
  if (Number.isNaN(merged) || Number.isNaN(live)) return null;
  if (live < merged) return null;
  return (live - merged) / 1000;
}

export function formatDuration(seconds: number | null): string {
  if (seconds == null) return "—";
  const s = Math.max(0, Math.floor(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ${m % 60}m`;
  const d = Math.floor(h / 24);
  return `${d}d ${h % 24}h`;
}

export type StatusVariant =
  | "default"
  | "secondary"
  | "destructive"
  | "success"
  | "warning"
  | "outline";

// Amplify job statuses that mean a deploy is mid-flight (ECS only ever
// reports IN_PROGRESS).
const IN_PROGRESS_STATUSES = new Set([
  "IN_PROGRESS",
  "PENDING",
  "PROVISIONING",
  "RUNNING",
  "CANCELLING",
]);

export function statusBadgeVariant(status: string | null): StatusVariant {
  if (status == null) return "outline";
  if (status === "COMPLETED" || status.toUpperCase().includes("SUCCEED")) {
    return "success";
  }
  if (IN_PROGRESS_STATUSES.has(status)) return "default";
  if (
    status === "FAILED" ||
    status === "CANCELLED" ||
    status === "error" ||
    status.toLowerCase().includes("unavailable")
  ) {
    return "destructive";
  }
  return "outline";
}

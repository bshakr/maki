import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import {
  fetchDeployTimeline,
  type DeployTimeline as Timeline,
  type TimelineSegment,
} from "@/api";
import { formatDuration } from "@/lib/format";
import { cn } from "@/lib/utils";

// Bright categorical palette from the Web-App Bento GanttChart. NO amber/red —
// those are reserved for status (in_progress / failed) so they never collide
// with a phase's own hue.
const PHASE_COLORS = [
  "#7c3aed", // violet
  "#2563eb", // blue
  "#059669", // green
  "#1ab3d9", // cyan
  "#fd6996", // pink
  "#6366f1", // indigo
  "#16b6a2", // teal
];

const STATUS_FAILED = "#dc2626"; // red
const STATUS_IN_PROGRESS = "#d97706"; // amber

// Minimum bar width (% of axis) so a near-instant phase is still visible.
const MIN_WIDTH_PCT = 0.5;

// Stable color per phase: a simple hash of the key, mod palette length, so a
// phase keeps its hue across renders regardless of ordering.
function hashKey(key: string): number {
  let h = 0;
  for (let i = 0; i < key.length; i++) {
    h = (h * 31 + key.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

function phaseColor(seg: TimelineSegment): string {
  if (seg.status === "failed") return STATUS_FAILED;
  if (seg.status === "in_progress") return STATUS_IN_PROGRESS;
  return PHASE_COLORS[hashKey(seg.key) % PHASE_COLORS.length];
}

function ms(iso: string | null): number | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  return Number.isNaN(t) ? null : t;
}

interface Row {
  seg: TimelineSegment;
  start: number | null;
  end: number | null;
  leftPct: number | null;
  widthPct: number | null;
}

interface Axis {
  axisStart: number;
  axisEnd: number;
  dur: number;
  rows: Row[];
  // Tail span [lastEnd, axisEnd] for the "no data" placeholder, or null when
  // not needed (ECS segments present, or no meaningful gap).
  tail: { leftPct: number; widthPct: number } | null;
}

function buildAxis(timeline: Timeline): Axis {
  const segStarts = timeline.segments
    .map((s) => ms(s.start))
    .filter((t): t is number => t !== null);
  const segEnds = timeline.segments
    .map((s) => ms(s.end))
    .filter((t): t is number => t !== null);

  const axisStart =
    ms(timeline.merged_at) ??
    (segStarts.length ? Math.min(...segStarts) : 0);
  const axisEnd =
    ms(timeline.live_at) ?? (segEnds.length ? Math.max(...segEnds) : axisStart);
  const dur = Math.max(axisEnd - axisStart, 1);

  // One row per segment, sorted by start (null-start last).
  const rows: Row[] = timeline.segments
    .map((seg) => {
      const start = ms(seg.start);
      const end = ms(seg.end);
      if (start === null || end === null) {
        return { seg, start, end, leftPct: null, widthPct: null };
      }
      return {
        seg,
        start,
        end,
        leftPct: ((start - axisStart) / dur) * 100,
        widthPct: Math.max(((end - start) / dur) * 100, MIN_WIDTH_PCT),
      };
    })
    .sort((a, b) => {
      if (a.start === null) return 1;
      if (b.start === null) return -1;
      return a.start - b.start;
    });

  // Dead-space tail: only when there are NO ECS segments and the axis end is
  // meaningfully after the last segment's end. The placeholder explains the
  // gap between CI finishing and the deploy being live.
  const hasEcs = timeline.segments.some((s) => s.source === "ecs");
  let tail: Axis["tail"] = null;
  if (!hasEcs && segEnds.length) {
    const lastEnd = Math.max(...segEnds);
    // "Meaningful" = at least 1% of the axis remains after the last phase.
    if ((axisEnd - lastEnd) / dur > 0.01) {
      tail = {
        leftPct: ((lastEnd - axisStart) / dur) * 100,
        widthPct: ((axisEnd - lastEnd) / dur) * 100,
      };
    }
  }

  return { axisStart, axisEnd, dur, rows, tail };
}

function TotalHeader({ totalSeconds }: { totalSeconds: number | null }) {
  return (
    <p className="text-sm text-muted-foreground">
      Time to prod ·{" "}
      <span className="font-medium tabular-nums text-foreground">
        {formatDuration(totalSeconds)}
      </span>
    </p>
  );
}

function GanttRow({ row }: { row: Row }) {
  const { seg, leftPct, widthPct } = row;
  const color = phaseColor(seg);
  const pulse = seg.status === "in_progress";
  // A zero-duration phase (or null) carries no signal: render it quiet —
  // muted text, smaller, and a faint tick at its start instead of a bar.
  const isZero = !seg.seconds;
  const positioned = leftPct !== null && widthPct !== null;

  return (
    <div className="flex items-center gap-3" data-testid="timeline-row">
      <div
        className={cn(
          "flex w-44 shrink-0 items-center gap-1.5",
          isZero ? "text-xs text-muted-foreground" : "text-sm",
        )}
      >
        <span className="truncate" title={seg.label}>
          {seg.label}
        </span>
        {seg.count > 1 && (
          <span className="shrink-0 rounded bg-muted px-1 text-xs tabular-nums text-muted-foreground">
            ×{seg.count}
          </span>
        )}
        <span className="ml-auto shrink-0 tabular-nums text-xs text-muted-foreground">
          {formatDuration(seg.seconds)}
        </span>
      </div>
      <div className="relative h-5 flex-1 rounded bg-muted/50">
        {positioned &&
          (isZero ? (
            <div
              data-testid="timeline-tick"
              className="absolute top-1/2 h-3 w-0.5 -translate-y-1/2 rounded-full bg-muted-foreground/40"
              style={{ left: `${leftPct}%` }}
              title={`${seg.label}${seg.count > 1 ? ` ×${seg.count}` : ""} · ${formatDuration(
                seg.seconds,
              )}`}
            />
          ) : (
            <div
              data-testid="timeline-bar"
              className={cn(
                "absolute top-0 h-full rounded",
                pulse && "animate-pulse",
              )}
              style={{
                left: `${leftPct}%`,
                width: `${widthPct}%`,
                backgroundColor: color,
              }}
              title={`${seg.label}${seg.count > 1 ? ` ×${seg.count}` : ""} · ${formatDuration(
                seg.seconds,
              )}`}
            />
          ))}
      </div>
    </div>
  );
}

function RunLinks({ urls }: { urls: string[] }) {
  if (urls.length === 0) return null;
  return (
    <p
      className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted-foreground"
      data-testid="timeline-run-links"
    >
      <a
        href={urls[0]}
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-center gap-0.5 underline-offset-4 hover:underline"
      >
        View CI run
        <ExternalLink className="size-3" aria-hidden />
      </a>
      {urls.slice(1).map((url, i) => (
        <a
          key={url}
          href={url}
          target="_blank"
          rel="noreferrer"
          className="text-xs underline-offset-4 hover:underline"
        >
          +{i + 1} more
        </a>
      ))}
    </p>
  );
}

function SectionSubhead({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
      {children}
    </p>
  );
}

function NoDataTail({ tail }: { tail: NonNullable<Axis["tail"]> }) {
  return (
    <div className="flex items-center gap-3" data-testid="timeline-nodata">
      <div className="flex w-44 shrink-0 items-center gap-1.5 text-sm text-muted-foreground">
        <span className="truncate" title="rollout">
          rollout
        </span>
        <span className="ml-auto shrink-0 rounded bg-muted px-1 text-xs text-muted-foreground">
          no data
        </span>
      </div>
      <div className="relative h-5 flex-1 rounded bg-muted/50">
        <div
          className="absolute top-0 h-full rounded bg-muted"
          style={{
            left: `${tail.leftPct}%`,
            width: `${tail.widthPct}%`,
            backgroundImage:
              "repeating-linear-gradient(45deg, transparent, transparent 4px, rgba(0,0,0,0.08) 4px, rgba(0,0,0,0.08) 8px)",
          }}
          title="rollout · no data"
        />
      </div>
    </div>
  );
}

function GanttViz({ timeline }: { timeline: Timeline }) {
  const axis = buildAxis(timeline);
  // Rows are already start-sorted by buildAxis; partitioning preserves that
  // order within each section.
  const ciRows = axis.rows.filter((r) => r.seg.source === "github_actions");
  const ecsRows = axis.rows.filter((r) => r.seg.source === "ecs");
  // The no-data band lives under Rollout, so that section is non-empty whenever
  // there are ECS rows OR the band is present.
  const showRollout = ecsRows.length > 0 || axis.tail !== null;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
        <TotalHeader totalSeconds={timeline.total_seconds} />
        <RunLinks urls={timeline.run_urls ?? []} />
      </div>
      <div className="flex flex-col gap-3" data-testid="timeline-gantt">
        {ciRows.length > 0 && (
          <div className="flex flex-col gap-1.5" data-testid="timeline-section-ci">
            <SectionSubhead>CI (GitHub Actions)</SectionSubhead>
            {ciRows.map((row) => (
              <GanttRow key={row.seg.key} row={row} />
            ))}
          </div>
        )}
        {showRollout && (
          <div
            className="flex flex-col gap-1.5"
            data-testid="timeline-section-rollout"
          >
            <SectionSubhead>Rollout (ECS)</SectionSubhead>
            {ecsRows.map((row) => (
              <GanttRow key={row.seg.key} row={row} />
            ))}
            {axis.tail && <NoDataTail tail={axis.tail} />}
          </div>
        )}
      </div>
      <p className="text-[11px] text-muted-foreground/80">
        Bars are wall-clock; rows may overlap in time (parallel CI).
      </p>
    </div>
  );
}

export function DeployTimeline({
  service,
  sha,
  revision,
  mergedAt,
}: {
  service: string;
  sha?: string;
  revision?: number;
  mergedAt?: string;
}) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["deploy-timeline", service, sha ?? null, revision ?? null, mergedAt ?? null],
    queryFn: () => fetchDeployTimeline(service, { sha, revision, mergedAt }),
  });

  let content: React.ReactNode;
  if (isLoading) {
    content = <Skeleton className="h-12 w-full" />;
  } else if (isError || !data?.segments) {
    content = (
      <p className="text-sm text-muted-foreground">Timeline unavailable</p>
    );
  } else if (data.segments.length === 0) {
    content = (
      <p className="text-sm text-muted-foreground">No timeline available</p>
    );
  } else {
    content = <GanttViz timeline={data} />;
  }

  return <div data-testid="deploy-timeline">{content}</div>;
}

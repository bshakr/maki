import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchMetrics, fetchTaskHistory, type TaskHistoryPoint } from "@/api";
import { ago, formatDuration } from "@/lib/format";
import { cn } from "@/lib/utils";

const RANGE_OPTIONS = [7, 30, 90] as const;

const chartConfig = {
  // Stacked so CI/build + rollout sum to the total lead time, day by day. Colors match
  // the CI-vs-rollout breakdown bar below (CI = chart-2, rollout = chart-1).
  ci_median_seconds: {
    label: "CI/build",
    color: "var(--color-chart-2)",
  },
  rollout_median_seconds: {
    label: "Rollout",
    color: "var(--color-chart-1)",
  },
} satisfies ChartConfig;

// Running task count over time (filled step area). Desired is intentionally not shown — for
// fixed-size services it's a flat line, and the running shape already tells the story.
const taskChartConfig = {
  running: {
    label: "Running",
    color: "var(--color-chart-1)",
  },
} satisfies ChartConfig;

// Compact date tick for the task-count x-axis, e.g. "2026-05-30T11:00:00Z" → "May 30".
function taskTick(value: string): string {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function StatTile({
  label,
  value,
  sub,
  background,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  background?: React.ReactNode;
}) {
  return (
    <Card className="relative overflow-hidden">
      {background != null && (
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-12 opacity-70">
          {background}
        </div>
      )}
      <CardHeader>
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {label}
        </CardTitle>
      </CardHeader>
      <CardContent className="relative">
        <div className="text-2xl font-semibold">{value}</div>
        {sub != null && (
          <div className="text-xs text-muted-foreground">{sub}</div>
        )}
      </CardContent>
    </Card>
  );
}

// Tiny axis-less area chart for a stat-card background (e.g. deploys/day over the range).
function Sparkline({ data }: { data: { date: string; count: number }[] }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={data} margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
        <Area
          dataKey="count"
          type="monotone"
          stroke="var(--color-chart-1)"
          strokeWidth={1}
          strokeOpacity={0.5}
          fill="var(--color-chart-1)"
          fillOpacity={0.15}
          dot={false}
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

function TasksOverTimeCard({
  points,
  isLoading,
}: {
  points: TaskHistoryPoint[] | undefined;
  isLoading: boolean;
}) {
  return (
    <Card data-testid="tasks-over-time">
      <CardHeader>
        <CardTitle className="text-sm font-medium text-muted-foreground">
          Tasks over time
        </CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading && !points ? (
          <Skeleton className="h-64 w-full" />
        ) : !points || points.length === 0 ? (
          <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
            No task data in this range.
          </div>
        ) : (
          <ChartContainer config={taskChartConfig} className="h-64 w-full">
            <AreaChart data={points} accessibilityLayer>
              <CartesianGrid vertical={false} />
              <XAxis
                dataKey="timestamp"
                tickLine={false}
                axisLine={false}
                tickMargin={8}
                minTickGap={24}
                tickFormatter={taskTick}
              />
              <YAxis
                tickLine={false}
                axisLine={false}
                width={32}
                allowDecimals={false}
                domain={[0, "auto"]}
              />
              <ChartTooltip
                content={
                  <ChartTooltipContent
                    labelFormatter={(_label, payload) =>
                      taskTick(String(payload?.[0]?.payload?.timestamp ?? ""))
                    }
                  />
                }
              />
              {/* Running task count as a filled step area (actual capacity over time). */}
              <Area
                dataKey="running"
                type="step"
                stroke="var(--color-running)"
                fill="var(--color-running)"
                fillOpacity={0.2}
                dot={false}
                connectNulls
              />
            </AreaChart>
          </ChartContainer>
        )}
      </CardContent>
    </Card>
  );
}

function MetricsTabSkeleton() {
  return (
    <div data-testid="metrics-tab" className="flex flex-col gap-4">
      <Skeleton className="h-9 w-44" />
      <Skeleton className="h-28 w-full" />
      <div className="grid gap-4 sm:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Card key={i}>
            <CardHeader>
              <Skeleton className="h-4 w-24" />
            </CardHeader>
            <CardContent>
              <Skeleton className="h-8 w-20" />
            </CardContent>
          </Card>
        ))}
      </div>
      <Skeleton className="h-64 w-full" />
    </div>
  );
}

export function MetricsTab({ service }: { service: string }) {
  const [rangeDays, setRangeDays] = useState(30);

  const { data, isLoading, isError, error, isFetching } = useQuery({
    queryKey: ["metrics", service, rangeDays],
    queryFn: () => fetchMetrics({ service, rangeDays }),
    placeholderData: keepPreviousData,
  });

  // Separate source/cache from /api/metrics; shares only the rangeDays selector. Guarded
  // independently so a task-history error never blocks the rest of the metrics tab.
  const taskHistory = useQuery({
    queryKey: ["task-history", service, rangeDays],
    queryFn: () => fetchTaskHistory(service, { rangeDays }),
    placeholderData: keepPreviousData,
  });

  if (isLoading && !data) {
    return <MetricsTabSkeleton />;
  }

  if (isError && !data) {
    return (
      <div
        data-testid="metrics-tab"
        role="alert"
        className="rounded-md border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive"
      >
        {error instanceof Error ? error.message : "Failed to load metrics"}
      </div>
    );
  }

  if (!data) return null;

  const rangeSelector = (
    <div
      role="group"
      aria-label="Time range"
      className="flex w-fit items-center gap-1 rounded-md border p-0.5"
    >
      {RANGE_OPTIONS.map((days) => (
        <Button
          key={days}
          type="button"
          size="sm"
          variant={rangeDays === days ? "secondary" : "ghost"}
          aria-pressed={rangeDays === days}
          className={cn("h-7 px-3 text-xs", rangeDays === days && "font-semibold")}
          onClick={() => setRangeDays(days)}
        >
          {days}d
        </Button>
      ))}
    </div>
  );

  if (data.deploy_count === 0) {
    return (
      <div data-testid="metrics-tab" className="flex flex-col gap-4">
        {rangeSelector}
        <Card>
          <CardContent className="flex h-40 items-center justify-center text-sm text-muted-foreground">
            No deploys in this range.
          </CardContent>
        </Card>
      </div>
    );
  }

  const ci = data.ci_median_seconds ?? 0;
  const rollout = data.rollout_median_seconds ?? 0;
  const breakdownTotal = ci + rollout;

  return (
    <div data-testid="metrics-tab" className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-2">
        {rangeSelector}
        {/* A refetch (e.g. range switch) keeps showing the previous range via keepPreviousData;
            surface its progress/failure so a stale body isn't mistaken for the selected range. */}
        {isError ? (
          <span className="text-xs text-destructive">
            Couldn’t refresh — showing previous range
          </span>
        ) : (
          <span className="text-xs text-muted-foreground">
            {isFetching ? "updating…" : `updated ${ago(data.generated_at)}`}
          </span>
        )}
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label="Time to deploy"
          value={formatDuration(data.lead_time_median_seconds)}
          sub={`p90 ${formatDuration(data.lead_time_p90_seconds)} · merged → live`}
        />
        <StatTile
          label="Deploy frequency"
          value={
            <>
              {data.deploys_per_day}
              <span className="ml-1 text-sm font-normal text-muted-foreground">
                /day
              </span>
            </>
          }
          sub={`${data.deploy_count} in last ${data.range_days}d`}
          background={<Sparkline data={data.trend} />}
        />
        <StatTile
          label="Rollout (median)"
          value={formatDuration(data.rollout_median_seconds)}
          sub="registered → live"
        />
        <StatTile label="Last deploy" value={ago(data.last_deployed_at)} />
      </div>

      {/* Lead-time trend */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium text-muted-foreground">
            Lead-time trend · CI + rollout
          </CardTitle>
        </CardHeader>
        <CardContent>
          <ChartContainer config={chartConfig} className="h-64 w-full">
            <AreaChart data={data.lead_time_trend} accessibilityLayer>
              <CartesianGrid vertical={false} />
              <XAxis
                dataKey="date"
                tickLine={false}
                axisLine={false}
                tickMargin={8}
                minTickGap={24}
              />
              <YAxis
                tickLine={false}
                axisLine={false}
                width={48}
                tickFormatter={(v) => formatDuration(Number(v))}
              />
              <ChartTooltip
                content={
                  <ChartTooltipContent
                    formatter={(value) => formatDuration(Number(value))}
                  />
                }
              />
              <ChartLegend content={<ChartLegendContent />} />
              <Area
                dataKey="ci_median_seconds"
                type="monotone"
                stackId="lead"
                connectNulls
                stroke="var(--color-ci_median_seconds)"
                fill="var(--color-ci_median_seconds)"
                fillOpacity={0.25}
              />
              <Area
                dataKey="rollout_median_seconds"
                type="monotone"
                stackId="lead"
                connectNulls
                stroke="var(--color-rollout_median_seconds)"
                fill="var(--color-rollout_median_seconds)"
                fillOpacity={0.25}
              />
            </AreaChart>
          </ChartContainer>
        </CardContent>
      </Card>

      {/* Tasks over time (autoscaling): desired vs running task counts */}
      <TasksOverTimeCard
        points={taskHistory.data?.points}
        isLoading={taskHistory.isLoading}
      />

      {/* CI vs rollout breakdown */}
      <Card data-testid="ci-rollout-breakdown">
        <CardHeader>
          <CardTitle className="text-sm font-medium text-muted-foreground">
            CI/build vs rollout (median)
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="flex h-3 w-full overflow-hidden rounded-full bg-muted">
            {breakdownTotal > 0 && (
              <>
                <div
                  className="h-full bg-chart-2"
                  style={{ width: `${(ci / breakdownTotal) * 100}%` }}
                  aria-hidden
                />
                <div
                  className="h-full bg-chart-1"
                  style={{ width: `${(rollout / breakdownTotal) * 100}%` }}
                  aria-hidden
                />
              </>
            )}
          </div>
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
            <div className="flex items-center gap-2">
              <span className="size-2.5 rounded-sm bg-chart-2" aria-hidden />
              <span className="text-muted-foreground">CI/build</span>
              <span className="font-medium">
                {formatDuration(data.ci_median_seconds)}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className="size-2.5 rounded-sm bg-chart-1" aria-hidden />
              <span className="text-muted-foreground">Rollout</span>
              <span className="font-medium">
                {formatDuration(data.rollout_median_seconds)}
              </span>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

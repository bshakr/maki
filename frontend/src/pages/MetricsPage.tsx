import { useRef, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ArrowDown, ArrowUp, Minus, RefreshCw } from "lucide-react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchMetrics, type DeployLeadEntry, type MetricBucket } from "@/api";
import { ago, formatDuration, shortSha } from "@/lib/format";

const RANGE_OPTIONS = [7, 30, 90] as const;

// ---------- DORA bands (standard thresholds, derived client-side) ----------

type Band = "Elite" | "High" | "Medium" | "Low";

const BAND_VARIANT: Record<Band, "success" | "default" | "warning" | "destructive"> = {
  Elite: "success",
  High: "default",
  Medium: "warning",
  Low: "destructive",
};

function freqBand(perDay: number): Band {
  if (perDay >= 1) return "Elite"; // multiple deploys/day → on-demand
  if (perDay >= 1 / 7) return "High"; // ≥ weekly
  if (perDay >= 1 / 30) return "Medium"; // ≥ monthly
  return "Low";
}
function leadBand(seconds: number | null): Band | null {
  if (seconds == null) return null;
  if (seconds <= 86400) return "Elite"; // < 1 day
  if (seconds <= 7 * 86400) return "High"; // < 1 week
  if (seconds <= 30 * 86400) return "Medium"; // < 1 month
  return "Low";
}
function cfrBand(fraction: number): Band {
  const pct = fraction * 100;
  if (pct <= 5) return "Elite";
  if (pct <= 10) return "High";
  if (pct <= 15) return "Medium";
  return "Low";
}
function mttrBand(seconds: number | null): Band | null {
  if (seconds == null) return null;
  if (seconds <= 3600) return "Elite"; // < 1 hour
  if (seconds <= 86400) return "High"; // < 1 day
  if (seconds <= 7 * 86400) return "Medium"; // < 1 week
  return "Low";
}

// ---------- small presentational pieces ----------

const sparkConfig = {
  v: { label: "value", color: "var(--color-chart-1)" },
} satisfies ChartConfig;

function hashStr(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (Math.imul(31, h) + s.charCodeAt(i)) | 0;
  return h;
}

/** Tiny inline area sparkline (no axes), tinted by `color`. */
function Sparkline({
  data,
  color = "var(--color-chart-1)",
  className = "h-9 w-full",
}: {
  data: number[];
  color?: string;
  className?: string;
}) {
  const id = `spark-${Math.abs(hashStr(data.join(",") + color))}`;
  const chartData = data.map((v, i) => ({ i, v }));
  return (
    <ChartContainer config={sparkConfig} className={className}>
      <AreaChart data={chartData} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.35} />
            <stop offset="100%" stopColor={color} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <Area
          dataKey="v"
          type="monotone"
          stroke={color}
          strokeWidth={1.75}
          fill={`url(#${id})`}
          isAnimationActive={false}
          dot={false}
        />
      </AreaChart>
    </ChartContainer>
  );
}

/** Colored ↑/↓ delta vs the previous period. `goodWhenDown` flips the good/bad coloring. */
function Delta({
  current,
  previous,
  goodWhenDown,
}: {
  current: number | null;
  previous: number | null;
  goodWhenDown?: boolean;
}) {
  if (current == null || previous == null) {
    return <span className="text-xs text-muted-foreground">—</span>;
  }
  const pct =
    previous === 0 ? (current === 0 ? 0 : 100) : ((current - previous) / previous) * 100;
  const flat = Math.abs(pct) < 0.5;
  const up = pct > 0;
  const good = flat ? false : goodWhenDown ? !up : up;
  const Icon = flat ? Minus : up ? ArrowUp : ArrowDown;
  return (
    <span
      data-testid="delta"
      data-direction={flat ? "flat" : up ? "up" : "down"}
      className={
        "inline-flex items-center gap-0.5 text-xs font-medium " +
        (flat
          ? "text-muted-foreground"
          : good
            ? "text-green-600 dark:text-green-400"
            : "text-destructive")
      }
    >
      <Icon className="size-3" aria-hidden />
      {Math.abs(pct).toFixed(0)}%
    </span>
  );
}

function KpiCard({
  title,
  value,
  unit,
  band,
  spark,
  sparkColor,
  delta,
}: {
  title: string;
  value: string;
  unit?: string;
  band: Band | null;
  spark: number[];
  sparkColor?: string;
  delta: React.ReactNode;
}) {
  return (
    <Card data-slot="card">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-1">
        <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
        {band && <Badge variant={BAND_VARIANT[band]}>{band}</Badge>}
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="flex items-baseline gap-1">
          <span className="text-3xl font-semibold tabular-nums">{value}</span>
          {unit && <span className="text-sm font-normal text-muted-foreground">{unit}</span>}
        </div>
        <div className="-mx-1">
          {spark.length > 1 ? (
            <Sparkline data={spark} color={sparkColor} className="h-9 w-full" />
          ) : (
            <div className="h-9" />
          )}
        </div>
        <div className="flex items-center gap-1 text-xs text-muted-foreground">
          {delta} <span>vs prev period</span>
        </div>
      </CardContent>
    </Card>
  );
}

const trendConfig = {
  success: { label: "Successful", color: "var(--color-chart-1)" },
  failed: { label: "Failed", color: "var(--color-chart-5)" },
} satisfies ChartConfig;

/** Merge the count trend with the fail trend into a stacked success/failed series per day. */
function buildDeployTrend(
  trend: MetricBucket[],
  failTrend: MetricBucket[],
): { date: string; success: number; failed: number }[] {
  const fails = new Map(failTrend.map((b) => [b.date, b.count]));
  return trend.map((b) => {
    const failed = fails.get(b.date) ?? 0;
    return {
      date: b.date.slice(5),
      success: Math.max(0, b.count - failed),
      failed,
    };
  });
}

function LeaderboardCard({
  title,
  entries,
  accent,
}: {
  title: string;
  entries: DeployLeadEntry[];
  accent: string;
}) {
  return (
    <Card data-slot="card">
      <CardHeader>
        <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        {entries.length === 0 ? (
          <div className="py-6 text-center text-sm text-muted-foreground">
            No deploys with a lead time
          </div>
        ) : (
          <ol className="flex flex-col gap-1.5">
            {entries.map((e, i) => {
              const sha = e.sha;
              const row = (
                <>
                  <span
                    className="w-4 shrink-0 text-right text-xs tabular-nums text-muted-foreground"
                    aria-hidden
                  >
                    {i + 1}
                  </span>
                  <span className="min-w-0 flex-1 truncate">
                    <span className="font-medium">{e.service}</span>
                    <span className="mx-1 text-muted-foreground">·</span>
                    <span className="font-mono text-xs">{shortSha(sha)}</span>
                    {e.author && (
                      <>
                        <span className="mx-1 text-muted-foreground">·</span>
                        <span className="text-muted-foreground">{e.author}</span>
                      </>
                    )}
                  </span>
                  <span
                    className="shrink-0 font-medium tabular-nums"
                    style={{ color: accent }}
                  >
                    {formatDuration(e.lead_seconds)}
                  </span>
                  <span className="w-16 shrink-0 text-right text-xs text-muted-foreground">
                    {ago(e.deployed_at)}
                  </span>
                </>
              );
              return (
                <li key={`${e.service}-${e.sha}-${i}`}>
                  {sha ? (
                    // Whole row links to that deploy's sheet on the service page.
                    <Link
                      to={`/services/${encodeURIComponent(e.service)}/deploys/${shortSha(sha)}`}
                      className="-mx-1.5 flex items-center gap-2 rounded-md px-1.5 py-1 text-sm transition-colors hover:bg-accent/50"
                    >
                      {row}
                    </Link>
                  ) : (
                    <div className="flex items-center gap-2 px-1.5 py-1 text-sm">
                      {row}
                    </div>
                  )}
                </li>
              );
            })}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}

function MetricsSkeleton() {
  return (
    <div data-testid="metrics-page" className="flex flex-col gap-4">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
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
      <Skeleton className="h-72 w-full" />
    </div>
  );
}

export function MetricsPage() {
  const [rangeDays, setRangeDays] = useState(30);
  const [service, setService] = useState("all");

  // When set, the next fetch (a manual Refresh) bypasses the server cache via
  // ?refresh=1. Background/interval refetches stay on the plain cached path.
  const forceNext = useRef(false);

  const { data, isLoading, isError, error, isFetching, refetch } = useQuery({
    queryKey: ["metrics", rangeDays, service],
    queryFn: () => {
      const refresh = forceNext.current;
      forceNext.current = false;
      return fetchMetrics({ rangeDays, service, refresh });
    },
    placeholderData: keepPreviousData,
  });

  function handleRefresh() {
    forceNext.current = true;
    refetch();
  }

  if (isLoading && !data) return <MetricsSkeleton />;

  if (isError && !data) {
    return (
      <div
        data-testid="metrics-page"
        role="alert"
        className="rounded-md border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive"
      >
        {error instanceof Error ? error.message : "Failed to load metrics"}
      </div>
    );
  }

  if (!data) return null;

  const prev = data.previous;
  const cfrPct = data.change_fail_rate * 100;
  const deployTrend = buildDeployTrend(data.trend, data.fail_trend);

  return (
    <div data-testid="metrics-page" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Select value={String(rangeDays)} onValueChange={(v) => setRangeDays(Number(v))}>
            <SelectTrigger size="sm" className="w-24">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {RANGE_OPTIONS.map((days) => (
                <SelectItem key={days} value={String(days)}>
                  {days}d
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={service} onValueChange={setService}>
            <SelectTrigger size="sm" className="w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">all services</SelectItem>
              {data.services.map((name) => (
                <SelectItem key={name} value={name}>
                  {name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex items-center gap-2">
          {isFetching && !isLoading && (
            <span className="text-xs text-muted-foreground">updating…</span>
          )}
          <Button variant="outline" size="sm" onClick={handleRefresh} disabled={isFetching}>
            <RefreshCw
              className={isFetching ? "size-3.5 animate-spin" : "size-3.5"}
              aria-hidden
            />
            Refresh
          </Button>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title="Deploy frequency"
          value={data.deploys_per_day.toFixed(2)}
          unit="/day"
          band={freqBand(data.deploys_per_day)}
          spark={data.trend.map((b) => b.count)}
          sparkColor="var(--color-chart-1)"
          delta={
            <Delta
              current={data.deploys_per_day}
              previous={prev?.deploys_per_day ?? null}
            />
          }
        />
        <KpiCard
          title="Lead time (median)"
          value={formatDuration(data.lead_time_median_seconds)}
          unit={
            data.lead_time_p90_seconds != null
              ? `p90 ${formatDuration(data.lead_time_p90_seconds)}`
              : undefined
          }
          band={leadBand(data.lead_time_median_seconds)}
          spark={data.lead_time_trend.map((b) => (b.median_seconds ?? 0) / 60)}
          sparkColor="var(--color-chart-2)"
          delta={
            <Delta
              current={data.lead_time_median_seconds}
              previous={prev?.lead_time_median_seconds ?? null}
              goodWhenDown
            />
          }
        />
        <KpiCard
          title="Change-fail rate"
          value={`${cfrPct.toFixed(1)}%`}
          band={cfrBand(data.change_fail_rate)}
          spark={data.fail_trend.map((b) => b.count)}
          sparkColor="var(--color-chart-5)"
          delta={
            <Delta
              current={data.change_fail_rate}
              previous={prev?.change_fail_rate ?? null}
              goodWhenDown
            />
          }
        />
        <KpiCard
          title="MTTR"
          value={formatDuration(data.mttr_median_seconds)}
          band={mttrBand(data.mttr_median_seconds)}
          spark={[]}
          sparkColor="var(--color-chart-4)"
          delta={
            <Delta
              current={data.mttr_median_seconds}
              previous={prev?.mttr_median_seconds ?? null}
              goodWhenDown
            />
          }
        />
      </div>

      <Card data-slot="card">
        <CardHeader>
          <CardTitle className="text-sm font-medium text-muted-foreground">
            Deploys over time
            <span className="ml-2 font-normal">
              · {data.deploy_count} deploys, {data.failed_count + data.rollback_count} failed
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {data.deploy_count === 0 ? (
            <div className="flex h-72 items-center justify-center text-sm text-muted-foreground">
              No deploys in the last {data.range_days}d
            </div>
          ) : (
            <ChartContainer config={trendConfig} className="h-72 w-full">
              <BarChart data={deployTrend} accessibilityLayer>
                <CartesianGrid vertical={false} />
                <XAxis
                  dataKey="date"
                  tickLine={false}
                  axisLine={false}
                  tickMargin={8}
                  minTickGap={24}
                />
                <YAxis allowDecimals={false} tickLine={false} axisLine={false} width={28} />
                <ChartTooltip content={<ChartTooltipContent />} />
                <Bar
                  dataKey="success"
                  stackId="d"
                  fill="var(--color-success)"
                  radius={[0, 0, 2, 2]}
                />
                <Bar
                  dataKey="failed"
                  stackId="d"
                  fill="var(--color-failed)"
                  radius={[2, 2, 0, 0]}
                />
              </BarChart>
            </ChartContainer>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <LeaderboardCard
          title="Slowest deploys"
          entries={data.slowest_deploys}
          accent="var(--color-chart-5)"
        />
        <LeaderboardCard
          title="Fastest deploys"
          entries={data.fastest_deploys}
          accent="var(--color-chart-1)"
        />
      </div>

      <p className="text-xs text-muted-foreground">updated {ago(data.generated_at)}</p>
    </div>
  );
}

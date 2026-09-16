import { useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw, Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { AuthorAvatar } from "@/components/author-avatar";
import { AwsCredsError } from "@/components/aws-creds-error";
import { PinButton } from "@/components/pin-button";
import { WatchButton } from "@/components/watch-button";
import {
  fetchDeployCount,
  fetchServices,
  isAwsCredentialsError,
  type DeployedService,
  type GroupingRule,
} from "@/api";
import { useConfig } from "@/components/config-provider";
import { healthOf, type Health, HEALTH_RANK } from "@/lib/health";
import { serviceDomain, OTHER_DOMAIN } from "@/lib/domains";
import { ago } from "@/lib/format";
import { cn } from "@/lib/utils";

// ─────────────────────────────────────────────────────────────────────────────
// SERVICES — the fleet "status board". Lives inside the shared Layout (sidebar),
// uses the Nory Card and the app typeface. Status is carried by ONE glowing,
// pulsing dot per card; cards stay neutral (no coloured border) so colour means
// something. A fleet hero (counts + proportion bar + stat cards) makes "is
// everything green?" a one-glance read.
// ─────────────────────────────────────────────────────────────────────────────

// Status colour lives in two places only: the glowing dot and the status word.
type HealthStyle = { label: string; dot: string; halo: string; glow: string; text: string };

const HEALTH: Record<Health, HealthStyle> = {
  healthy: {
    label: "stable",
    dot: "bg-emerald-500",
    halo: "bg-emerald-500/60",
    glow: "shadow-[0_0_6px_1px_rgba(16,185,129,0.5)]",
    text: "text-emerald-600 dark:text-emerald-400",
  },
  deploying: {
    label: "deploying",
    dot: "bg-amber-500",
    halo: "bg-amber-400/70",
    glow: "shadow-[0_0_8px_2px_rgba(245,158,11,0.55)]",
    text: "text-amber-600 dark:text-amber-400",
  },
  error: {
    label: "degraded",
    dot: "bg-red-500",
    halo: "bg-red-500/40",
    glow: "shadow-[0_0_10px_2px_rgba(239,68,68,0.6)]",
    text: "text-red-600 dark:text-red-400",
  },
};

// One glowing status dot — deploying gets an expanding ping, degraded a slow
// pulsing halo, healthy a steady glow. The single status cue per card.
function StatusDot({ health }: { health: Health }) {
  const hs = HEALTH[health];
  return (
    <span
      className="relative flex size-2 shrink-0 items-center justify-center"
      aria-label={hs.label}
    >
      {health === "deploying" && (
        <span className={cn("absolute inline-flex size-full animate-ping rounded-full", hs.halo)} />
      )}
      {health === "error" && (
        <span className={cn("absolute inline-flex size-3.5 animate-pulse rounded-full", hs.halo)} />
      )}
      <span className={cn("relative inline-flex size-2 rounded-full", hs.dot, hs.glow)} />
    </span>
  );
}

type Counts = { healthy: number; deploying: number; error: number; total: number };

function countHealth(svcs: DeployedService[]): Counts {
  const c: Counts = { healthy: 0, deploying: 0, error: 0, total: svcs.length };
  for (const s of svcs) c[healthOf(s)]++;
  return c;
}

type FleetStats = {
  tasksRunning: number;
  tasksDesired: number;
  understaffed: boolean;
  deploysToday: number | null; // null until the activity feed loads
  reservedVcpu: number | null; // null when no service reports a reservation
  reservedGb: number | null;
};

// All from live data: task counts + reservations from /api/services, deploys
// today from the activity feed. ECS cpu units: 1024 = 1 vCPU; memory in MB.
function computeStats(svcs: DeployedService[], deploysToday: number | null): FleetStats {
  let tasksRunning = 0;
  let tasksDesired = 0;
  let cpu = 0;
  let mem = 0;
  let hasReservation = false;
  for (const s of svcs) {
    tasksRunning += s.running_count ?? 0;
    tasksDesired += s.desired_count ?? 0;
    if (s.cpu_reservation != null) {
      cpu += s.cpu_reservation;
      hasReservation = true;
    }
    if (s.mem_reservation != null) {
      mem += s.mem_reservation;
      hasReservation = true;
    }
  }
  return {
    tasksRunning,
    tasksDesired,
    understaffed: tasksRunning < tasksDesired,
    deploysToday,
    reservedVcpu: hasReservation ? Math.round((cpu / 1024) * 10) / 10 : null,
    reservedGb: hasReservation ? Math.round((mem / 1024) * 10) / 10 : null,
  };
}

function StatCard({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "warn";
}) {
  return (
    <div className="flex min-w-[88px] flex-col justify-center rounded-lg border bg-card px-3 py-2">
      <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div
        className={cn(
          "text-sm font-semibold tabular-nums",
          tone === "warn" && "text-amber-600 dark:text-amber-400",
        )}
      >
        {value}
      </div>
      {sub && <div className="text-[11px] text-muted-foreground tabular-nums">{sub}</div>}
    </div>
  );
}

type DomainGroup = { domain: string; services: DeployedService[]; counts: Counts };

// Severity-first: error groups first, then deploying, then alphabetical; "Other"
// pinned last. Services within a group are severity-sorted too.
function groupByDomain(
  services: DeployedService[],
  rules: GroupingRule[],
): DomainGroup[] {
  const map = new Map<string, DeployedService[]>();
  for (const s of services) {
    const d = serviceDomain(s.name, rules);
    (map.get(d) ?? map.set(d, []).get(d)!).push(s);
  }
  const groups: DomainGroup[] = [];
  for (const [domain, svcs] of map) {
    svcs.sort((a, b) => {
      const r = HEALTH_RANK[healthOf(a)] - HEALTH_RANK[healthOf(b)];
      return r !== 0 ? r : a.name.localeCompare(b.name);
    });
    groups.push({ domain, services: svcs, counts: countHealth(svcs) });
  }
  return groups.sort((a, b) => {
    const aOther = a.domain === OTHER_DOMAIN;
    const bOther = b.domain === OTHER_DOMAIN;
    if (aOther !== bOther) return aOther ? 1 : -1;
    const rank = (g: DomainGroup) => (g.counts.error > 0 ? 0 : g.counts.deploying > 0 ? 1 : 2);
    const ar = rank(a);
    const br = rank(b);
    if (ar !== br) return ar - br;
    return a.domain.localeCompare(b.domain);
  });
}

// ── Fleet hero ───────────────────────────────────────────────────────────────
function ProportionBar({ counts }: { counts: Counts }) {
  const seg = (n: number) => `${(n / Math.max(1, counts.total)) * 100}%`;
  return (
    <div
      className="flex h-2.5 w-full overflow-hidden rounded-full bg-muted ring-1 ring-inset ring-border"
      role="img"
      aria-label={`${counts.healthy} stable, ${counts.deploying} deploying, ${counts.error} degraded of ${counts.total} services`}
    >
      <div className="h-full bg-emerald-500/80" style={{ width: seg(counts.healthy) }} />
      <div className="board-shimmer h-full bg-amber-500" style={{ width: seg(counts.deploying) }} />
      {counts.error > 0 && (
        <div className="board-pulse h-full bg-red-500" style={{ width: seg(counts.error) }} />
      )}
    </div>
  );
}

function Stat({ n, label, health, muted }: { n: number; label: string; health: Health; muted?: boolean }) {
  const hs = HEALTH[health];
  return (
    <div className="flex flex-col">
      <div className="flex items-center gap-2">
        <span className={cn("size-2 rounded-full", muted ? "bg-muted-foreground/40" : cn(hs.dot, hs.glow))} />
        <span className={cn("text-3xl font-semibold leading-none tabular-nums", muted ? "text-muted-foreground" : "text-foreground")}>
          {String(n).padStart(2, "0")}
        </span>
      </div>
      <span className="mt-1.5 pl-4 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </span>
    </div>
  );
}

function FleetHero({
  counts,
  stats,
  env,
  region,
  syncedAt,
  query,
  setQuery,
  onRefresh,
  refreshing,
}: {
  counts: Counts;
  stats: FleetStats;
  env: string;
  region: string | null;
  syncedAt: string | null;
  query: string;
  setQuery: (v: string) => void;
  onRefresh: () => void;
  refreshing: boolean;
}) {
  const allGreen = counts.error === 0;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-center gap-2.5">
          <span className="flex items-center gap-1.5 rounded-full border bg-muted/40 px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
            <span className="relative flex size-1.5">
              <span className="board-ping absolute inline-flex size-full rounded-full bg-emerald-500 opacity-75" />
              <span className="relative inline-flex size-1.5 rounded-full bg-emerald-500" />
            </span>
            {env}
            {region && <span className="text-muted-foreground/60">· {region}</span>}
          </span>
          {syncedAt && (
            <span className="text-xs text-muted-foreground">synced {ago(syncedAt)}</span>
          )}
        </div>

        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Filter services…"
              aria-label="Filter services"
              className="h-8 w-48 pl-8"
            />
          </div>
          <Button variant="outline" size="sm" onClick={onRefresh} disabled={refreshing}>
            <RefreshCw className={refreshing ? "size-3.5 animate-spin" : "size-3.5"} aria-hidden />
            Refresh
          </Button>
        </div>
      </div>

      <div className="grid gap-x-6 gap-y-4 lg:grid-cols-[minmax(0,1fr)_auto]">
        <div className="flex min-w-0 flex-col gap-4">
          <div className="flex items-end gap-7">
            <Stat n={counts.healthy} label="stable" health="healthy" />
            <Stat n={counts.deploying} label="deploying" health="deploying" />
            <Stat n={counts.error} label="degraded" health="error" muted={counts.error === 0} />
            <span
              className={cn(
                "ml-auto self-center text-xs font-medium",
                allGreen
                  ? "text-emerald-600 dark:text-emerald-400"
                  : "text-amber-600 dark:text-amber-400",
              )}
            >
              {allGreen ? "All systems nominal" : "Active deploys in flight"}
            </span>
          </div>

          <ProportionBar counts={counts} />
        </div>

        <div className="grid grid-cols-3 gap-2">
          <StatCard
            label="Tasks"
            value={`${stats.tasksRunning}/${stats.tasksDesired}`}
            tone={stats.understaffed ? "warn" : undefined}
          />
          <StatCard
            label="Deploys today"
            value={stats.deploysToday == null ? "—" : String(stats.deploysToday)}
          />
          <StatCard
            label="Reserved"
            value={stats.reservedVcpu == null ? "—" : `${stats.reservedVcpu} vCPU`}
            sub={stats.reservedGb == null ? undefined : `${stats.reservedGb} GB`}
          />
        </div>
      </div>
    </div>
  );
}

// ── Domain header ────────────────────────────────────────────────────────────
function DomainHeader({ domain, counts }: { domain: string; counts: Counts }) {
  return (
    <div className="mb-3 flex items-center gap-3">
      <h2 className="text-sm font-semibold">{domain}</h2>
      <div className="h-px flex-1 bg-border" />
      <div className="flex items-center gap-2.5 text-xs text-muted-foreground tabular-nums">
        {counts.error > 0 && (
          <span className="flex items-center gap-1 text-red-600 dark:text-red-400">
            <span className="size-1.5 rounded-full bg-red-500" />
            {counts.error}
          </span>
        )}
        {counts.deploying > 0 && (
          <span className="flex items-center gap-1 text-amber-600 dark:text-amber-400">
            <span className="size-1.5 rounded-full bg-amber-500" />
            {counts.deploying}
          </span>
        )}
        <span className="flex items-center gap-1 text-emerald-600/80 dark:text-emerald-400/80">
          <span className="size-1.5 rounded-full bg-emerald-500" />
          {counts.healthy}
        </span>
        <span className="text-muted-foreground/60">/ {counts.total}</span>
      </div>
    </div>
  );
}

// ── Service card (Nory Card) ─────────────────────────────────────────────────
function ServiceCard({ svc, index, onOpen }: { svc: DeployedService; index: number; onOpen: (name: string) => void }) {
  const { watches_enabled } = useConfig();
  const health = healthOf(svc);
  const hs = HEALTH[health];
  const deploying = health === "deploying";
  const tasks = `${svc.running_count ?? 0}/${svc.desired_count ?? 0}`;
  const subline = health === "error" && svc.rollout_reason ? svc.rollout_reason : svc.message;

  function open() {
    onOpen(svc.name);
  }

  return (
    <Card
      onClick={open}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          open();
        }
      }}
      role="link"
      tabIndex={0}
      aria-label={`${svc.name} — ${hs.label}, ${tasks} tasks, updated ${ago(svc.deployed_at)}`}
      className="group board-tile-in cursor-pointer gap-2 py-3 transition-colors hover:bg-accent/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      style={{ animationDelay: `${Math.min(index, 18) * 28}ms` }}
    >
      <CardContent className="flex flex-col gap-2">
        <div className="flex items-start justify-between gap-2">
          <div className="truncate font-medium leading-none" title={svc.name}>
            {svc.name}
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {/* Pinned/watched services keep their control visible; otherwise it
                surfaces on hover / keyboard focus so cards stay uncluttered. */}
            {watches_enabled && (
              <WatchButton
                name={svc.name}
                size="icon-xs"
                className="opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100 aria-pressed:opacity-100"
              />
            )}
            <PinButton
              name={svc.name}
              size="icon-xs"
              className="opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100 aria-pressed:opacity-100"
            />
            <StatusDot health={health} />
          </div>
        </div>

        {subline && (
          <div className="flex min-w-0 items-center gap-1.5">
            <AuthorAvatar
              name={svc.author}
              src={svc.author_avatar_url}
              className="size-4 shrink-0"
            />
            <div
              className={cn(
                "line-clamp-1 text-xs",
                health === "error" && svc.rollout_reason
                  ? "text-red-600 dark:text-red-400"
                  : "text-muted-foreground",
              )}
              title={subline}
            >
              {subline}
            </div>
          </div>
        )}

        {deploying && svc.rollout_progress != null && (
          <div className="h-1 w-full overflow-hidden rounded-full bg-amber-500/15">
            <div
              className="board-shimmer h-full rounded-full bg-amber-500"
              style={{ width: `${Math.max(0, Math.min(100, svc.rollout_progress))}%` }}
            />
          </div>
        )}

        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {/* Healthy is the boring default — the dot says it. Only label trouble. */}
          {health !== "healthy" && (
            <span className={cn("font-medium", hs.text)}>{hs.label}</span>
          )}
          <span className="ml-auto flex shrink-0 items-center gap-1 tabular-nums">
            <span title="running / desired tasks">{tasks} tasks</span>
            <span aria-hidden>·</span>
            <span>{ago(svc.deployed_at)}</span>
          </span>
        </div>
      </CardContent>
    </Card>
  );
}

// ── Skeleton ─────────────────────────────────────────────────────────────────
function GridSkeleton() {
  return (
    <div className="flex flex-col gap-6">
      {Array.from({ length: 2 }).map((_, s) => (
        <div key={s}>
          <div className="mb-3 flex items-center gap-3">
            <Skeleton className="h-4 w-28" />
            <div className="h-px flex-1 bg-border" />
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {Array.from({ length: 8 }).map((_, i) => (
              <Card key={i} className="gap-2 py-3">
                <CardContent className="flex flex-col gap-2">
                  <Skeleton className="h-4 w-32" />
                  <Skeleton className="h-3 w-40" />
                  <Skeleton className="h-3 w-20" />
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────
export function ServicesPage() {
  const navigate = useNavigate();
  const forceNext = useRef(false);
  const [query, setQuery] = useState("");

  const { data, isLoading, isError, error, isFetching, refetch } = useQuery({
    queryKey: ["services"],
    queryFn: () => {
      const refresh = forceNext.current;
      forceNext.current = false;
      return fetchServices({ refresh });
    },
    refetchInterval: 15_000,
  });

  const todayUtc = new Date().toISOString().slice(0, 10);
  const { data: deployCount } = useQuery({
    queryKey: ["deploy-count", todayUtc],
    queryFn: () => fetchDeployCount(`${todayUtc}T00:00:00Z`),
    refetchInterval: 15_000,
  });
  const deploysToday = deployCount?.count ?? null;

  function onRefresh() {
    forceNext.current = true;
    refetch();
  }

  const services = data?.services ?? [];
  const counts = useMemo(() => countHealth(services), [services]);

  const stats = useMemo(
    () => computeStats(services, deploysToday),
    [services, deploysToday],
  );

  const { grouping_rules } = useConfig();

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return services;
    return services.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        (s.message ?? "").toLowerCase().includes(q) ||
        serviceDomain(s.name, grouping_rules).toLowerCase().includes(q),
    );
  }, [services, query, grouping_rules]);

  const groups = useMemo(
    () => groupByDomain(filtered, grouping_rules),
    [filtered, grouping_rules],
  );

  const env = services.find((s) => s.env)?.env ?? "production";
  const region = services.find((s) => s.region)?.region ?? null;

  return (
    <div data-testid="services-page" className="flex flex-col gap-4">
      <BoardStyles />
      <FleetHero
        counts={counts}
        stats={stats}
        env={env}
        region={region}
        syncedAt={data?.generated_at ?? null}
        query={query}
        setQuery={setQuery}
        onRefresh={onRefresh}
        refreshing={isFetching}
      />

      {isLoading && !data ? (
        <GridSkeleton />
      ) : isError && !data ? (
        isAwsCredentialsError(error) ? (
          <AwsCredsError onRetry={onRefresh} retrying={isFetching} />
        ) : (
          <div
            role="alert"
            className="rounded-md border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive"
          >
            {error instanceof Error ? error.message : "Failed to load services"}
          </div>
        )
      ) : groups.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {query ? `No services match “${query}”.` : "No services deployed."}
        </p>
      ) : (
        <div className="flex flex-col gap-6">
          {groups.map(({ domain, services: svcs, counts: c }) => (
            <section key={domain}>
              <DomainHeader domain={domain} counts={c} />
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {svcs.map((svc, i) => (
                  <ServiceCard
                    key={svc.name}
                    svc={svc}
                    index={i}
                    onOpen={(name) => navigate(`/services/${name}`)}
                  />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}

function BoardStyles() {
  return (
    <style>{`
      @keyframes board-tile-in {
        from { opacity: 0; transform: translateY(8px) scale(0.985); }
        to   { opacity: 1; transform: translateY(0) scale(1); }
      }
      .board-tile-in { animation: board-tile-in 0.4s cubic-bezier(0.22, 1, 0.36, 1) both; }

      @keyframes board-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
      .board-pulse { animation: board-pulse 1.4s ease-in-out infinite; }

      @keyframes board-ping { 75%, 100% { transform: scale(2.2); opacity: 0; } }
      .board-ping { animation: board-ping 1.8s cubic-bezier(0,0,0.2,1) infinite; }

      @keyframes board-shimmer { 0% { background-position: -200% 0; } 100% { background-position: 200% 0; } }
      .board-shimmer {
        background-image: linear-gradient(110deg, transparent 30%, rgba(255,255,255,0.45) 50%, transparent 70%);
        background-size: 200% 100%;
        background-blend-mode: overlay;
        animation: board-shimmer 1.8s linear infinite;
      }
    `}</style>
  );
}

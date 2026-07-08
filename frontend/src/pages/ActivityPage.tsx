import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Crosshair, X, Loader2, Pause, Play, RefreshCw } from "lucide-react";

import { ActivityDeployCard } from "@/components/activity-deploy-card";
import { DateTimePicker } from "@/components/date-time-picker";
import { ServiceMultiSelect } from "@/components/service-multiselect";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  fetchActivity,
  fetchActivityAround,
  type ActivityItem,
  type ActivityResponse,
} from "@/api";
import { ago, toLocalInput } from "@/lib/format";
import { cn } from "@/lib/utils";

// "Jump to timestamp" fetches deploys around the target — a fixed ±N-hour window
// gives before/after context without making the window a user-facing knob.
const JUMP_WINDOW_HOURS = 6;

// Live-tail cadence: how often the latest feed re-polls while tailing is ON.
const LIVE_POLL_MS = 5_000;

// The current local moment, so the picker opens on "now" by default.
function localNowInput(): string {
  return toLocalInput(new Date());
}

// A pulsing dot for the live indicator — same treatment as the deploy-status
// LiveDot, kept local so the page doesn't depend on the proto module.
function LiveDot({ className }: { className?: string }) {
  return (
    <span className={cn("relative flex size-2", className)} aria-hidden>
      <span className="absolute inline-flex size-full animate-ping rounded-full bg-current opacity-75" />
      <span className="relative inline-flex size-2 rounded-full bg-current" />
    </span>
  );
}

// Mirrors ActivityDeployCard's layout (avatar · service+message / meta · badge)
// so the loading state has the same rhythm as the real feed and doesn't reflow.
function ActivityCardSkeleton() {
  return (
    <div className="flex items-center gap-3 rounded-lg border px-4 py-3.5">
      <Skeleton className="size-6 shrink-0 rounded-full" />
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div className="flex items-center gap-2">
          <Skeleton className="h-4 w-28" />
          <Skeleton className="h-3.5 w-40 max-w-[45%]" />
        </div>
        <Skeleton className="h-3 w-52 max-w-[60%]" />
      </div>
      <Skeleton className="h-5 w-10 shrink-0 rounded-md" />
    </div>
  );
}

function ActivityListSkeleton() {
  return (
    <div data-testid="activity-skeleton" className="flex flex-col gap-3">
      {Array.from({ length: 6 }).map((_, i) => (
        <ActivityCardSkeleton key={i} />
      ))}
    </div>
  );
}

interface JumpQuery {
  around: string; // ISO-8601 (UTC) — what the API receives
  windowHours: number;
  targetMs: number; // target as epoch ms, for placing the marker
}

// The "← you jumped here" marker line, anchored so the page can scroll to it.
function JumpMarker({
  label,
  markerRef,
}: {
  label: string;
  markerRef?: React.Ref<HTMLDivElement>;
}) {
  return (
    <div
      ref={markerRef}
      data-testid="jump-marker"
      className="flex items-center gap-3 py-1"
      aria-label={`Jumped to ${label}`}
    >
      <div className="h-px flex-1 bg-primary/40" />
      <span className="flex items-center gap-1.5 rounded-full border border-primary/40 bg-primary/10 px-3 py-1 text-xs font-medium text-primary">
        <Crosshair className="size-3" aria-hidden />
        you jumped here · {label}
      </span>
      <div className="h-px flex-1 bg-primary/40" />
    </div>
  );
}

// Shown on the side of the marker (before or after) that has no deploys, so the
// "before vs after" framing reads clearly even when one side is empty.
function SideNote({ text }: { text: string }) {
  return (
    <p className="px-1 py-2 text-center text-xs text-muted-foreground">
      {text}
    </p>
  );
}

export function ActivityPage() {
  const [searchParams, setSearchParams] = useSearchParams();

  // A shareable jump lives in the URL as ?at=<ISO>&w=<hours>. Read it once on
  // mount so a pasted link lands directly on that moment; later URL writes all
  // come from our own handlers, so there's no state⇄URL feedback loop.
  const urlJump = useMemo<JumpQuery | null>(() => {
    const at = searchParams.get("at");
    if (!at) return null;
    const d = new Date(at);
    if (Number.isNaN(d.getTime())) return null;
    return {
      around: d.toISOString(),
      windowHours: JUMP_WINDOW_HOURS,
      targetMs: d.getTime(),
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Selected service names; empty = show all. A Set keeps membership checks O(1)
  // for the filter predicate below.
  const [selectedServices, setSelectedServices] = useState<string[]>([]);

  // "Jump to timestamp" control state. `pickerValue` is the raw datetime-local string;
  // `jump` is the committed query that actually drives the fetch (null = latest feed).
  const [pickerValue, setPickerValue] = useState(() =>
    urlJump ? toLocalInput(new Date(urlJump.targetMs)) : localNowInput(),
  );
  const [jump, setJump] = useState<JumpQuery | null>(urlJump);

  // Live tail: when ON (default), the latest feed auto-polls; Pause stops it.
  // A jump freezes the feed to investigate, so tailing is conceptually off while
  // jumped regardless of this flag — `isTailing` below combines the two.
  const [livePaused, setLivePaused] = useState(false);

  // When set, the next fetch (a manual Refresh) bypasses the server cache via
  // ?refresh=1. Background/interval refetches stay on the plain cached path.
  const forceNext = useRef(false);
  const markerRef = useRef<HTMLDivElement | null>(null);

  // Tailing is live only on the latest feed, while not paused. A jump freezes it.
  const isTailing = !jump && !livePaused;

  // Default (latest) feed: keyset-paginated via useInfiniteQuery so "Load more" appends older
  // pages. Disabled while a jump is active. Page 1 carries no cursor; later pages use the previous
  // page's `next_cursor`. `refresh` only affects page 1 (the cached server entry).
  //
  // `refetchInterval` explicitly overrides the shared queryClient default: LIVE_POLL_MS while
  // tailing, `false` when paused (or jumped, where the query is disabled anyway). This is the
  // live-tail engine — Pause flips it off, Resume flips it back on.
  const feed = useInfiniteQuery({
    queryKey: ["activity"],
    enabled: !jump,
    initialPageParam: undefined as string | undefined,
    refetchInterval: isTailing ? LIVE_POLL_MS : false,
    queryFn: ({ pageParam }) => {
      // Manual Refresh bypasses the server cache on the first (cursor-less) page only.
      const refresh = pageParam === undefined && forceNext.current;
      if (pageParam === undefined) forceNext.current = false;
      return fetchActivity({ refresh, cursor: pageParam });
    },
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
  });

  // Jump (windowed) feed: a bounded ±N-hour query, never paginated. Disabled unless jumping.
  // Never auto-refreshes — a frozen window is the whole point of jumping.
  const around = useQuery({
    queryKey: ["activity", "around", jump?.around, jump?.windowHours],
    enabled: !!jump,
    refetchInterval: false,
    queryFn: () => fetchActivityAround(jump!.around, jump!.windowHours),
  });

  // Flatten the active source into one shape the rest of the component already understands.
  const data: ActivityResponse | undefined = jump
    ? around.data
    : feed.data
      ? {
          items: feed.data.pages.flatMap((p) => p.items),
          // The freshness footer reflects the most recently fetched page.
          generated_at: feed.data.pages[feed.data.pages.length - 1].generated_at,
          next_cursor:
            feed.data.pages[feed.data.pages.length - 1].next_cursor,
        }
      : undefined;

  const isLoading = jump ? around.isLoading : feed.isLoading;
  const isError = jump ? around.isError : feed.isError;
  const error = jump ? around.error : feed.error;
  const isFetching = jump ? around.isFetching : feed.isFetching;
  // True only while fetching an additional page, so page-1 refetches don't disable Load-more.
  const isFetchingNextPage = feed.isFetchingNextPage;
  const hasMore = !jump && (feed.hasNextPage ?? false);

  function handleRefresh() {
    forceNext.current = true;
    if (jump) around.refetch();
    else feed.refetch();
  }

  function handleLoadMore() {
    if (!jump) feed.fetchNextPage();
  }

  function handleJump() {
    if (!pickerValue) return;
    // datetime-local has no timezone; interpret it as local time and convert to ISO/UTC.
    const target = new Date(pickerValue);
    if (Number.isNaN(target.getTime())) return;
    setJump({
      around: target.toISOString(),
      windowHours: JUMP_WINDOW_HOURS,
      targetMs: target.getTime(),
    });
    // Reflect the jump in the URL so the view is shareable / deep-linkable.
    setSearchParams({ at: target.toISOString() }, { replace: true });
  }

  function clearJump() {
    setJump(null);
    setSearchParams({}, { replace: true });
    // Resume live tailing — "Back to latest" means back to the live edge.
    setLivePaused(false);
  }

  // Options come straight from whatever's loaded (all paginated pages, or the
  // jump window) — unique service names, sorted. No extra API call.
  const serviceOptions = useMemo(() => {
    if (!data) return [];
    return [...new Set(data.items.map((item) => item.service))].sort((a, b) =>
      a.localeCompare(b),
    );
  }, [data]);

  const filtered = useMemo(() => {
    if (!data) return [];
    if (selectedServices.length === 0) return data.items;
    const selected = new Set(selectedServices);
    return data.items.filter((item) => selected.has(item.service));
  }, [data, selectedServices]);

  // Split the (newest-first) list into the events newer than the target and those at/older
  // than it, so the marker can sit exactly at the crossover — what deployed just before/after.
  const { newer, older } = useMemo(() => {
    if (!jump) return { newer: filtered, older: [] as ActivityItem[] };
    const newerList: ActivityItem[] = [];
    const olderList: ActivityItem[] = [];
    for (const item of filtered) {
      const t = item.deployed_at ? new Date(item.deployed_at).getTime() : 0;
      if (t > jump.targetMs) newerList.push(item);
      else olderList.push(item);
    }
    return { newer: newerList, older: olderList };
  }, [filtered, jump]);

  // After a jump fetch settles, scroll the marker into view so the eye lands on the moment.
  useEffect(() => {
    if (jump && !isFetching && markerRef.current) {
      markerRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [jump, isFetching, data]);

  if (isLoading && !data) {
    return (
      <div data-testid="activity-page" className="flex flex-col gap-4">
        <ActivityListSkeleton />
      </div>
    );
  }

  if (isError && !data) {
    return (
      <div
        data-testid="activity-page"
        role="alert"
        className="rounded-md border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive"
      >
        {error instanceof Error ? error.message : "Failed to load activity"}
      </div>
    );
  }

  if (!data) return null;

  const jumpLabel = jump
    ? new Date(jump.targetMs).toLocaleString(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      })
    : "";

  function renderCard(item: ActivityItem) {
    return <ActivityDeployCard key={item.id} item={item} />;
  }

  // Live-indicator copy. Frozen while jumped; LIVE while tailing; PAUSED otherwise.
  const freshness = `updated ${ago(data.generated_at)}`;

  return (
    <div data-testid="activity-page" className="flex flex-col gap-4">
      {/* Live Tail Console: one calm bar. Left = live status; right = Filters · Jump · Pause. */}
      <div className="flex flex-wrap items-center gap-3 rounded-xl border bg-muted/50 px-3 py-2">
        {/* Left: live status + freshness, folded into one indicator. */}
        <div
          data-testid="live-indicator"
          className="flex items-center gap-2 text-sm"
        >
          {jump ? (
            <>
              <span className="flex items-center text-muted-foreground" aria-hidden>
                <Pause className="size-3.5" />
              </span>
              <span className="font-medium tracking-wide text-muted-foreground">
                FROZEN
              </span>
            </>
          ) : isTailing ? (
            <>
              <span className="flex items-center text-primary">
                <LiveDot className="text-primary" />
              </span>
              <span className="font-medium tracking-wide text-foreground">
                LIVE
              </span>
            </>
          ) : (
            <>
              <span
                className="font-medium tracking-wide text-muted-foreground"
                aria-hidden
              >
                ‖
              </span>
              <span className="font-medium tracking-wide text-muted-foreground">
                PAUSED
              </span>
            </>
          )}
          <span className="text-muted-foreground" aria-hidden>
            ·
          </span>
          <span className="text-xs text-muted-foreground tabular-nums">
            {isFetching && !isLoading ? "updating…" : freshness}
          </span>
        </div>

        {/* Right cluster (ml-auto): Filters · Jump · Pause/Resume. */}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <ServiceMultiSelect
            options={serviceOptions}
            selected={selectedServices}
            onChange={setSelectedServices}
          />
          <DateTimePicker
            value={pickerValue}
            onChange={setPickerValue}
            onJump={handleJump}
          />
          {jump ? (
            // While frozen, the only live action is returning to the latest edge.
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={clearJump}
              aria-label="Clear jump"
            >
              <X className="size-3.5" aria-hidden />
              Back to latest
            </Button>
          ) : (
            <div className="flex items-center gap-1.5">
              {/* Manual refresh stays available while paused so investigation isn't
                  stuck on stale data; hidden while tailing (polling handles it). */}
              {livePaused && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={handleRefresh}
                  disabled={isFetching}
                  aria-label="Refresh now"
                  title="Refresh now"
                >
                  <RefreshCw
                    className={isFetching ? "size-3.5 animate-spin" : "size-3.5"}
                    aria-hidden
                  />
                </Button>
              )}
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setLivePaused((p) => !p)}
                aria-pressed={livePaused}
                data-testid="live-toggle"
              >
                {livePaused ? (
                  <>
                    <Play className="size-3.5" aria-hidden />
                    Resume
                  </>
                ) : (
                  <>
                    <Pause className="size-3.5" aria-hidden />
                    Pause
                  </>
                )}
              </Button>
            </div>
          )}
        </div>
      </div>

      {jump && (
        <p className="text-xs text-muted-foreground">
          Showing deploys around{" "}
          <span className="font-medium text-foreground">{jumpLabel}</span>.
        </p>
      )}

      {filtered.length > 0 ? (
        jump ? (
          <div className="flex flex-col gap-3">
            {newer.length ? (
              newer.map(renderCard)
            ) : (
              <SideNote text="No deploys just after" />
            )}
            <JumpMarker label={jumpLabel} markerRef={markerRef} />
            {older.length ? (
              older.map(renderCard)
            ) : (
              <SideNote text="No deploys just before" />
            )}
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {filtered.map(renderCard)}
            {hasMore && (
              <div className="flex justify-center pt-1">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleLoadMore}
                  disabled={isFetchingNextPage}
                >
                  {isFetchingNextPage ? (
                    <Loader2 className="size-3.5 animate-spin" aria-hidden />
                  ) : null}
                  {isFetchingNextPage ? "Loading…" : "Load more"}
                </Button>
              </div>
            )}
          </div>
        )
      ) : (
        <div className="rounded-lg border px-4 py-8 text-center text-sm text-muted-foreground">
          {jump
            ? `No deploys around ${jumpLabel}.`
            : selectedServices.length > 0
              ? "No activity matches the selected services."
              : "No recent activity."}
        </div>
      )}
    </div>
  );
}

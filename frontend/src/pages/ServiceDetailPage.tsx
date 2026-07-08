import { useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Loader2, RefreshCw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  fetchDeploy,
  fetchDeployments,
  fetchServices,
  type DeployedService,
  type DeployRecord,
} from "@/api";
import { AuthorAvatar } from "@/components/author-avatar";
import { CurrentDeploySection } from "@/components/current-deploy-section";
import {
  STATE_BORDER,
  StatusMarker,
  deployState,
} from "@/components/deploy-status";
import { EnvTab } from "@/components/env-tab";
import { MetricsTab } from "@/components/metrics-tab";
import { ServiceTabs } from "@/components/service-tabs";
import { deriveServiceTab } from "@/lib/service-tabs";
import { DeployDetailSheet } from "@/components/deploy-detail-sheet";
import { RollbackDialog } from "@/components/rollback-dialog";
import { RunTaskSheet } from "@/components/run-task-sheet";
import { withCurrentDeploy } from "@/lib/deployments";
import {
  ago,
  formatDuration,
  leadTimeSeconds,
  shortSha,
  timestamp,
  timestampPrecise,
} from "@/lib/format";
import { cn } from "@/lib/utils";

function PlaceholderCard({ title }: { title: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent className="text-sm text-muted-foreground">
        Coming next.
      </CardContent>
    </Card>
  );
}

function DeployHistoryItem({
  d,
  onRollback,
  onOpen,
}: {
  d: DeployRecord;
  onRollback: (target: DeployRecord) => void;
  onOpen: (target: DeployRecord) => void;
}) {
  const lead = leadTimeSeconds(d.committed_at, d.finished_at);
  // Same status treatment as the activity feed: rollback/failed/in-progress get a coloured edge +
  // a marker badge so an incident-relevant deploy pops while scanning history.
  const state = deployState(d);
  return (
    <div
      data-state={state}
      className={cn(
        "flex items-center gap-3 rounded-lg border px-4 py-3.5 transition-colors hover:bg-accent/40",
        STATE_BORDER[state],
      )}
    >
      <div
        role="button"
        tabIndex={0}
        onClick={() => onOpen(d)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onOpen(d);
          }
        }}
        className="flex min-w-0 flex-1 cursor-pointer flex-col gap-1.5"
      >
        <div className="flex items-center gap-2">
          <AuthorAvatar
            name={d.author}
            src={d.author_avatar_url}
            className="shrink-0"
          />
          <span className="truncate text-sm font-medium">
            {d.message ?? <span className="text-muted-foreground">—</span>}
          </span>
          <Badge
            variant="outline"
            className="shrink-0 text-[10px] font-normal text-muted-foreground"
          >
            not live
          </Badge>
        </div>
        <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
          {d.commit_url && d.sha ? (
            <a
              href={d.commit_url}
              target="_blank"
              rel="noreferrer"
              className="font-mono underline-offset-4 hover:underline"
            >
              {shortSha(d.sha)}
            </a>
          ) : (
            <span className="font-mono">{shortSha(d.sha)}</span>
          )}
          <span aria-hidden>·</span>
          <span>{d.author ?? "—"}</span>
          <span aria-hidden>·</span>
          <span
            className="tabular-nums"
            title={`${timestampPrecise(d.registered_at)} (${ago(d.registered_at)})`}
          >
            {timestamp(d.registered_at)}
          </span>
          {lead != null && (
            <>
              <span aria-hidden>·</span>
              <span title="merged → live">{formatDuration(lead)}</span>
            </>
          )}
        </span>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <StatusMarker state={state} />
        <Button
          size="sm"
          variant="outline"
          disabled={!d.sha}
          onClick={(e) => {
            e.stopPropagation();
            if (d.sha) onRollback(d);
          }}
        >
          Roll back
        </Button>
      </div>
    </div>
  );
}

function DeployHistory({
  deployments,
  loading,
  isError,
  currentSha,
  hasMore,
  isLoadingMore,
  onLoadMore,
  onRollback,
  onOpen,
}: {
  deployments: DeployRecord[] | undefined;
  loading: boolean;
  isError: boolean;
  currentSha: string | null;
  hasMore: boolean;
  isLoadingMore: boolean;
  onLoadMore: () => void;
  onRollback: (target: DeployRecord) => void;
  onOpen: (target: DeployRecord) => void;
}) {
  // The newest deploy is the one shown in the current-deploy section above —
  // drop it here so history shows only the *earlier* deploys.
  const history = (deployments ?? []).filter((d) => d.sha !== currentSha);

  // `deployments` is the merged set (live current folded in), so it's non-empty as soon
  // as the live service loads — emptiness of `history` no longer means "still loading".
  // Branch on whether the history fetch is in flight / errored, not on the merged list.
  let content: React.ReactNode;
  if (history.length > 0) {
    content = (
      <div className="flex flex-col gap-3">
        {history.map((d, i) => (
          <DeployHistoryItem
            // Prefer the stable DB id; the synthesized live-current row has no id, so fall back to
            // its sha (always present), then a positional key as a last resort.
            key={d.id ?? d.sha ?? `${d.revision ?? "rev"}-${i}`}
            d={d}
            onRollback={onRollback}
            onOpen={onOpen}
          />
        ))}
        {hasMore && (
          <div className="flex justify-center pt-1">
            <Button
              variant="outline"
              size="sm"
              onClick={onLoadMore}
              disabled={isLoadingMore}
            >
              {isLoadingMore ? (
                <Loader2 className="size-3.5 animate-spin" aria-hidden />
              ) : null}
              {isLoadingMore ? "Loading…" : "Load more"}
            </Button>
          </div>
        )}
      </div>
    );
  } else if (loading) {
    content = (
      <div className="flex flex-col gap-2">
        <Skeleton className="h-14 w-full" />
        <Skeleton className="h-14 w-full" />
        <Skeleton className="h-14 w-full" />
      </div>
    );
  } else if (isError) {
    content = (
      <div role="alert" className="text-sm text-destructive">
        Failed to load deployments
      </div>
    );
  } else {
    content = (
      <div className="text-sm text-muted-foreground">No earlier deploys.</div>
    );
  }

  return <div data-testid="deploy-history">{content}</div>;
}

export function ServiceDetailPage() {
  const { name, sha: deploySha } = useParams();
  const navigate = useNavigate();
  const activeTab = deriveServiceTab(useLocation().pathname);

  // When set, the next fetch (a manual Refresh) bypasses the server cache via
  // ?refresh=1. Background/interval refetches stay on the plain cached path.
  const forceServices = useRef(false);
  const forceDeployments = useRef(false);

  const [rollbackOpen, setRollbackOpen] = useState(false);
  const [rollbackTarget, setRollbackTarget] = useState<DeployRecord | null>(
    null,
  );
  const [runTaskOpen, setRunTaskOpen] = useState(false);

  function openRollback(target: DeployRecord | null) {
    setRollbackTarget(target);
    setRollbackOpen(true);
  }

  // The detail sheet is URL-driven: /services/:name/deploys/:sha. Clicking a deploy
  // pushes that path (shareable + bookmarkable); closing returns to the bare service URL.
  function openDetail(target: DeployRecord) {
    if (!name || !target.sha) return;
    navigate(`/services/${encodeURIComponent(name)}/deploys/${shortSha(target.sha)}`);
  }

  function closeDetail() {
    if (name) navigate(`/services/${encodeURIComponent(name)}`);
  }

  const {
    data: servicesData,
    isLoading: loading,
    isError,
    isFetching: servicesFetching,
    refetch: refetchServices,
  } = useQuery({
    queryKey: ["services"],
    queryFn: () => {
      const refresh = forceServices.current;
      forceServices.current = false;
      return fetchServices({ refresh });
    },
    refetchInterval: 15_000,
  });
  const services: DeployedService[] | undefined = servicesData?.services;

  // Deploy history: keyset-paginated via useInfiniteQuery so "Load more" appends older pages,
  // mirroring the activity feed. Page 1 carries no cursor; later pages use the previous page's
  // `next_cursor`. `refresh` (manual Refresh) only affects page 1 (the cached server entry).
  const {
    data: deploymentsData,
    isLoading: deployLoading,
    isError: deployIsError,
    isFetching: deploymentsFetching,
    isFetchingNextPage,
    hasNextPage,
    fetchNextPage,
    refetch: refetchDeployments,
  } = useInfiniteQuery({
    queryKey: ["deployments", name],
    enabled: !!name,
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) => {
      const refresh = pageParam === undefined && forceDeployments.current;
      if (pageParam === undefined) forceDeployments.current = false;
      return fetchDeployments(name!, { refresh, cursor: pageParam });
    },
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
  });
  // Flatten every loaded page into one list the rest of the page already understands.
  const deployments: DeployRecord[] | undefined = deploymentsData
    ? deploymentsData.pages.flatMap((p) => p.deployments)
    : undefined;

  const isFetching = servicesFetching || deploymentsFetching;

  const currentSvc = services?.find((s) => s.name === name);

  // Reconcile the two reads: fold the live current deploy (inventory) into the history
  // dataset, deduped by sha. The history fetch and the inventory fetch have independent
  // SWR caches; merging keeps the current-deploy card, the history list, and the deep-link
  // sheet all resolving the same "current", even when one cache briefly lags the other.
  const mergedDeployments = withCurrentDeploy(deployments, currentSvc);

  // Resolve the URL's short sha to a full deploy record from what's already loaded (the merged set
  // always carries the current deploy + the loaded history pages), so a deep link to a current or
  // recent sha opens its sheet immediately with no extra request.
  const inListDeploy = deploySha
    ? (mergedDeployments?.find((d) => d.sha && shortSha(d.sha) === deploySha) ?? null)
    : null;

  // A deep link to a slowest/fastest (or otherwise old) sha won't be in the loaded window — the
  // metrics leaderboards link straight to it. When the sha isn't in the list, fetch that one deploy
  // by prefix. Enabled only once we know it's missing (deploySha set, list loaded, not found),
  // so the current/recent fast path above never triggers a request. A 404 resolves to null and the
  // sheet simply stays closed (bad sha -> no regression).
  const needsSingleFetch =
    !!deploySha && deployments !== undefined && inListDeploy === null;
  const { data: fetchedDeploy } = useQuery({
    queryKey: ["deploy", name, deploySha],
    enabled: !!name && needsSingleFetch,
    queryFn: () => fetchDeploy(name!, deploySha!),
  });

  const selectedDeploy = inListDeploy ?? fetchedDeploy ?? null;

  function handleRefresh() {
    forceServices.current = true;
    forceDeployments.current = true;
    refetchServices();
    refetchDeployments();
  }

  // Service-level actions live on the tab row (right side) so they sit flush at
  // the top and stay available on every tab.
  const tabActions = (
    <>
      {isFetching && (
        <span className="text-xs text-muted-foreground">updating…</span>
      )}
      <Button
        variant="outline"
        size="sm"
        onClick={handleRefresh}
        disabled={isFetching}
      >
        <RefreshCw
          className={isFetching ? "size-3.5 animate-spin" : "size-3.5"}
          aria-hidden
        />
        Refresh
      </Button>
      <Button
        variant="outline"
        size="sm"
        onClick={() => setRunTaskOpen(true)}
        disabled={!currentSvc}
      >
        Run task
      </Button>
    </>
  );

  let body: React.ReactNode;

  if (loading && !services) {
    body = (
      <div className="flex flex-col gap-3">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  } else if (isError && !services) {
    body = (
      <div
        role="alert"
        className="rounded-md border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive"
      >
        Failed to load services
      </div>
    );
  } else {
    const svc = currentSvc;

    if (!svc) {
      body = (
        <Card data-testid="service-not-found">
          <CardHeader>
            <CardTitle>Service not found</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4 text-sm text-muted-foreground">
            <p>No service named “{name}” was found.</p>
            <Button asChild variant="outline" size="sm" className="w-fit">
              <Link to="/">Back to services</Link>
            </Button>
          </CardContent>
        </Card>
      );
    } else {
      body = (
        <div className="flex flex-col gap-4">
          <ServiceTabs name={svc.name} active={activeTab} actions={tabActions} />

          {activeTab === "deploys" && (
            <>
              <CurrentDeploySection svc={svc} />
              <DeployHistory
                deployments={mergedDeployments}
                loading={deployLoading}
                isError={deployIsError}
                currentSha={svc.git_sha}
                hasMore={hasNextPage ?? false}
                isLoadingMore={isFetchingNextPage}
                onLoadMore={() => fetchNextPage()}
                onRollback={(target) => openRollback(target)}
                onOpen={(target) => openDetail(target)}
              />
            </>
          )}
          {activeTab === "tasks" && <PlaceholderCard title="Tasks" />}
          {activeTab === "metrics" && <MetricsTab service={svc.name} />}
          {activeTab === "env" && <EnvTab service={svc.name} />}
        </div>
      );
    }
  }

  return (
    <div data-testid="service-detail" className="flex flex-col gap-4">
      {body}
      {currentSvc && (
        <RollbackDialog
          open={rollbackOpen}
          onOpenChange={setRollbackOpen}
          service={currentSvc.name}
          currentSha={currentSvc.git_sha}
          target={rollbackTarget}
        />
      )}
      {currentSvc && (
        <RunTaskSheet
          open={runTaskOpen}
          onOpenChange={setRunTaskOpen}
          service={currentSvc.name}
          taskDef={null}
        />
      )}
      {currentSvc && (
        <DeployDetailSheet
          open={!!deploySha && !!selectedDeploy}
          onOpenChange={(open) => {
            if (!open) closeDetail();
          }}
          service={currentSvc.name}
          deploy={selectedDeploy}
          currentSha={currentSvc.git_sha}
        />
      )}
    </div>
  );
}

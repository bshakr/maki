import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, ChevronDown, Copy, ScrollText } from "lucide-react";

import { AuthorAvatar } from "@/components/author-avatar";
import { DeployTimeline } from "@/components/deploy-timeline";
import { LogsSheet } from "@/components/logs-sheet";
import { PinButton } from "@/components/pin-button";
import { fetchDeployTimeline, fetchRollout } from "@/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import type { DeployedService, RolloutDeployment } from "@/api";
import { useConfig } from "@/components/config-provider";
import { cloudWatchLogsUrl } from "@/lib/aws-console";
import {
  ago,
  compactImage,
  formatDuration,
  leadTimeSeconds,
  shortSha,
  statusBadgeVariant,
} from "@/lib/format";
import { healthOf, HEALTH_PRESENTATION, healthWord, type Health } from "@/lib/health";
import { cn } from "@/lib/utils";

// Health word color: degraded pops red, deploying amber, stable stays calm.
const HEALTH_WORD_CLASS: Record<Health, string> = {
  healthy: "text-foreground",
  deploying: "text-amber-600 dark:text-amber-400",
  error: "text-destructive",
};

// Derive the PR number from a github pull URL by taking the trailing segment.
function prNumber(prUrl: string | null): string | null {
  if (!prUrl) return null;
  return prUrl.split("/").filter(Boolean).pop() ?? null;
}

function ShaLink({ svc }: { svc: DeployedService }) {
  if (svc.commit_url && svc.git_sha) {
    return (
      <a
        href={svc.commit_url}
        target="_blank"
        rel="noreferrer"
        className="font-mono underline-offset-4 hover:underline"
      >
        {shortSha(svc.git_sha)}
      </a>
    );
  }
  return <span className="font-mono">{shortSha(svc.git_sha)}</span>;
}

function PrLink({ svc }: { svc: DeployedService }) {
  const n = prNumber(svc.pr_url);
  if (!svc.pr_url || !n) return null;
  return (
    <a
      href={svc.pr_url}
      target="_blank"
      rel="noreferrer"
      className="underline-offset-4 hover:underline"
    >
      PR #{n}
    </a>
  );
}

function CopyImage({ svc }: { svc: DeployedService }) {
  const [copied, setCopied] = useState(false);

  function copy() {
    if (!svc.image) return;
    void navigator.clipboard.writeText(svc.image);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  return (
    <span className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
      <span className="truncate font-mono" title={svc.image ?? undefined}>
        {compactImage(svc.image)}
      </span>
      {svc.image && (
        <Button
          type="button"
          variant="ghost"
          size="icon-xs"
          className="shrink-0"
          onClick={copy}
          aria-label="Copy image URI"
        >
          {copied ? (
            <Check className="size-3.5" aria-hidden />
          ) : (
            <Copy className="size-3.5" aria-hidden />
          )}
        </Button>
      )}
    </span>
  );
}

function taskCountClass(svc: DeployedService): string | undefined {
  const understaffed =
    svc.running_count != null &&
    svc.desired_count != null &&
    svc.running_count < svc.desired_count;
  return understaffed ? "text-destructive" : undefined;
}

function Tile({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5 rounded-lg border bg-muted/30 px-4 py-3">
      <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
        {label}
      </span>
      <span className="text-lg leading-none font-semibold">{children}</span>
    </div>
  );
}

function StatusTile({ svc }: { svc: DeployedService }) {
  const health = healthOf(svc);
  const p = HEALTH_PRESENTATION[health];
  return (
    <Tile label="Status">
      <span className={cn("flex items-center gap-2", HEALTH_WORD_CLASS[health])}>
        <span className={cn("size-2 rounded-full", p.dot)} aria-hidden />
        {healthWord(health)}
      </span>
    </Tile>
  );
}

// One line per deployment: the PRIMARY's rollout state + task counts, or an
// ACTIVE deployment's still-draining count.
function RolloutLine({ deployment }: { deployment: RolloutDeployment }) {
  if (deployment.status === "PRIMARY") {
    return (
      <div className="flex items-center gap-2 text-sm">
        <Badge variant={statusBadgeVariant(deployment.rollout_state)}>
          {deployment.rollout_state ?? "UNKNOWN"}
        </Badge>
        <span className="tabular-nums text-muted-foreground">
          {deployment.running_count ?? "—"} running · {deployment.pending_count ?? "—"} pending ·
          of {deployment.desired_count ?? "—"} desired
        </span>
      </div>
    );
  }
  return (
    <div className="flex items-center gap-2 text-sm">
      <Badge variant="outline">draining</Badge>
      <span className="tabular-nums text-muted-foreground">
        {deployment.running_count ?? "—"} still running
      </span>
    </div>
  );
}

function RolloutBlock({ rollout }: { rollout: RolloutDeployment[] }) {
  return (
    <div className="flex flex-col gap-2 rounded-lg border bg-muted/30 px-4 py-3">
      <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
        Rollout
      </span>
      <div className="flex flex-col gap-1.5">
        {rollout.map((deployment, i) => (
          <RolloutLine key={`${deployment.status}-${deployment.task_definition ?? i}`} deployment={deployment} />
        ))}
      </div>
    </div>
  );
}

export function CurrentDeploySection({ svc }: { svc: DeployedService }) {
  // The deploy timeline resolves the accurate "went live" moment from the ECS
  // rollout's finishedAt. We prefer it over svc.deployed_at — which is the ECS
  // primary deployment's updatedAt and drifts hours past the rollout as tasks
  // are recycled/scaled, inflating both "Deployed" and "Time to prod". Same query
  // key as the embedded <DeployTimeline/>, so the two never disagree and the call
  // is shared. Falls back to the inventory values when ECS data is unavailable.
  const { data: timeline } = useQuery({
    queryKey: ["deploy-timeline", svc.name, null, null, null],
    queryFn: () => fetchDeployTimeline(svc.name),
  });
  const liveAt = timeline?.live_at ?? svc.deployed_at;
  const leadSeconds =
    timeline?.total_seconds ?? leadTimeSeconds(svc.committed_at, svc.deployed_at);

  // Polls at 4s only while a rollout is in progress; otherwise a single fetch. Amplify has no
  // ECS deployments array, so the query is disabled there.
  const { data: rollout } = useQuery({
    queryKey: ["rollout", svc.name],
    queryFn: () => fetchRollout(svc.name),
    enabled: svc.platform === "ecs",
    refetchInterval: (query) => (query.state.data?.in_progress ? 4_000 : false),
  });

  const { aws_region, log_group_template } = useConfig();
  const [logsOpen, setLogsOpen] = useState(false);
  const logsUrl = cloudWatchLogsUrl(
    svc.name,
    svc.region,
    log_group_template,
    aws_region,
  );

  return (
    <Card>
      <CardContent className="flex flex-col gap-5">
        <div className="flex items-start justify-between gap-2">
          <h1 className="text-2xl font-semibold tracking-tight break-words">
            {svc.name}
          </h1>
          {/* Not nested in a clickable container here, but keep the default
              propagation guard harmless. */}
          <PinButton name={svc.name} className="mt-0.5 shrink-0" />
        </div>

        <div className="grid max-w-2xl grid-cols-2 gap-3 sm:grid-cols-4">
          <StatusTile svc={svc} />
          <Tile label="Tasks">
            <span className={cn("tabular-nums", taskCountClass(svc))}>
              {svc.running_count ?? "—"} / {svc.desired_count ?? "—"}
            </span>
          </Tile>
          <Tile label="Deployed">{ago(liveAt)}</Tile>
          <Tile label="Time to prod">
            <span className="flex flex-col gap-0.5">
              <span className="tabular-nums">{formatDuration(leadSeconds)}</span>
              <span className="text-[10px] font-normal tracking-normal text-muted-foreground normal-case">
                merged → live
              </span>
            </span>
          </Tile>
        </div>

        {rollout && (rollout.in_progress || rollout.deployments.length > 1) && (
          <RolloutBlock rollout={rollout.deployments} />
        )}

        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <AuthorAvatar
              name={svc.author}
              src={svc.author_avatar_url}
              className="shrink-0"
            />
            <p className="min-w-0 truncate text-base leading-snug font-medium">
              {svc.message ?? (
                <span className="text-muted-foreground">No commit message</span>
              )}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <ShaLink svc={svc} />
            {prNumber(svc.pr_url) && (
              <>
                <span aria-hidden>·</span>
                <PrLink svc={svc} />
              </>
            )}
            {svc.author && (
              <>
                <span aria-hidden>·</span>
                <span>{svc.author}</span>
              </>
            )}
          </div>
          <CopyImage svc={svc} />
        </div>

        <Collapsible className="group">
          <div className="flex flex-wrap items-center gap-2">
            {svc.platform === "ecs" && (
              <Button
                variant="outline"
                size="sm"
                className="gap-1.5"
                onClick={() => setLogsOpen(true)}
              >
                <ScrollText className="size-4 shrink-0" aria-hidden />
                Logs
              </Button>
            )}
            <CollapsibleTrigger asChild>
              <Button variant="outline" size="sm" className="gap-1.5">
                <ChevronDown
                  className="size-4 shrink-0 transition-transform group-data-[state=open]:rotate-180"
                  aria-hidden
                />
                View timeline
              </Button>
            </CollapsibleTrigger>
          </div>
          <CollapsibleContent className="pt-4">
            <DeployTimeline service={svc.name} />
          </CollapsibleContent>
        </Collapsible>

        {svc.platform === "ecs" && (
          <LogsSheet
            open={logsOpen}
            onOpenChange={setLogsOpen}
            service={svc.name}
            consoleUrl={logsUrl}
          />
        )}
      </CardContent>
    </Card>
  );
}

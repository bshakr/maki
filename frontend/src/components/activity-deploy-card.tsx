import { Link } from "react-router-dom";

import { AuthorAvatar } from "@/components/author-avatar";
import { Badge } from "@/components/ui/badge";
import {
  STATE_BORDER,
  StatusMarker,
  deployState,
} from "@/components/deploy-status";
import type { ActivityItem } from "@/api";
import {
  ago,
  formatDuration,
  leadTimeSeconds,
  shortSha,
  timestamp,
  timestampPrecise,
} from "@/lib/format";
import { cn } from "@/lib/utils";

// A fleet-wide deploy card: leads with the service (Activity spans every service),
// then the commit. The whole card links to that deploy's sheet on the service page
// (/services/:name/deploys/:sha), so it's shareable + opens the PR + timeline.
export function ActivityDeployCard({ item }: { item: ActivityItem }) {
  const lead = leadTimeSeconds(item.committed_at, item.deployed_at);
  const state = deployState(item);
  const to = item.sha
    ? `/services/${encodeURIComponent(item.service)}/deploys/${shortSha(item.sha)}`
    : `/services/${encodeURIComponent(item.service)}`;

  return (
    <Link
      to={to}
      data-testid="activity-card"
      data-state={state}
      className={cn(
        "flex items-center gap-3 rounded-lg border px-4 py-3.5 transition-colors hover:bg-accent/40",
        STATE_BORDER[state],
      )}
    >
      <AuthorAvatar
        name={item.author}
        src={item.author_avatar_url}
        className="shrink-0"
      />
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <div className="flex items-center gap-2">
          <span className="shrink-0 font-medium">{item.service}</span>
          <span className="min-w-0 truncate text-sm text-muted-foreground">
            {item.message ?? "—"}
          </span>
        </div>
        <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <span className="font-mono">{shortSha(item.sha)}</span>
          <span aria-hidden>·</span>
          <span>{item.author ?? "—"}</span>
          <span aria-hidden>·</span>
          <span
            className="tabular-nums"
            title={`${timestampPrecise(item.deployed_at)} (${ago(item.deployed_at)})`}
          >
            {timestamp(item.deployed_at)}
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
        <Badge variant="secondary">
          {item.platform === "amplify" ? "amp" : "ecs"}
        </Badge>
      </div>
    </Link>
  );
}

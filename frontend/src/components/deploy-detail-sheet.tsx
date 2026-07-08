import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { fetchPullDescription, type DeployRecord } from "@/api";
import { AuthorAvatar } from "@/components/author-avatar";
import { DeployTimeline } from "@/components/deploy-timeline";
import { ago, formatDuration, leadTimeSeconds, shortSha } from "@/lib/format";

// Derive the PR number from a pr_url's trailing path segment (digits only).
// e.g. "https://github.com/acme/platform/pull/4242" → 4242. null if absent/non-numeric.
function prNumberFrom(prUrl: string | null): number | null {
  if (!prUrl) return null;
  const last = prUrl.split("/").pop();
  if (!last || !/^\d+$/.test(last)) return null;
  return Number(last);
}

function SectionSubhead({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
      {children}
    </p>
  );
}

function PrDescription({
  service,
  prNumber,
  prUrl,
}: {
  service: string;
  prNumber: number;
  prUrl: string;
}) {
  const { data, isLoading } = useQuery({
    queryKey: ["pull", service, prNumber],
    queryFn: () => fetchPullDescription(service, prNumber),
  });

  let body: React.ReactNode;
  if (isLoading) {
    body = <Skeleton className="h-16 w-full" />;
  } else if (data?.body_excerpt || data?.title) {
    body = (
      <div className="flex flex-col gap-2">
        {data.title && (
          <p className="text-sm font-medium text-foreground">{data.title}</p>
        )}
        {data.body_excerpt && (
          <p className="text-xs leading-relaxed whitespace-pre-wrap text-muted-foreground">
            {data.body_excerpt}
          </p>
        )}
      </div>
    );
  } else {
    body = (
      <p className="text-sm text-muted-foreground">No PR description.</p>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <SectionSubhead>PR description</SectionSubhead>
      {body}
      <a
        href={prUrl}
        target="_blank"
        rel="noreferrer"
        className="inline-flex w-fit items-center gap-1 text-xs font-medium text-primary hover:underline"
      >
        <ExternalLink className="size-3" aria-hidden />
        View PR
      </a>
    </div>
  );
}

export function DeployDetailSheet({
  open,
  onOpenChange,
  service,
  deploy,
  currentSha,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  service: string;
  deploy: DeployRecord | null;
  currentSha?: string | null;
}) {
  const prNumber = deploy ? prNumberFrom(deploy.pr_url) : null;
  const lead = deploy
    ? leadTimeSeconds(deploy.committed_at, deploy.finished_at)
    : null;
  const isLive = Boolean(deploy?.sha && currentSha && deploy.sha === currentSha);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        data-testid="deploy-detail-sheet"
        className="sm:max-w-xl w-full overflow-y-auto"
      >
        {deploy && (
          <>
            <SheetHeader className="gap-3 border-b px-6 pt-6 pb-5 pr-14">
              <SheetTitle className="flex items-start gap-2.5 text-base leading-snug">
                <AuthorAvatar
                  name={deploy.author}
                  src={deploy.author_avatar_url}
                  className="mt-0.5 shrink-0"
                />
                <span className="min-w-0 break-words">
                  {deploy.message ?? "—"}
                </span>
              </SheetTitle>
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5 text-xs text-muted-foreground">
                {deploy.commit_url && deploy.sha ? (
                  <a
                    href={deploy.commit_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-0.5 font-mono underline-offset-4 hover:underline"
                  >
                    {shortSha(deploy.sha)}
                    <ExternalLink className="size-3" aria-hidden />
                  </a>
                ) : (
                  <span className="font-mono">{shortSha(deploy.sha)}</span>
                )}
                {prNumber != null && deploy.pr_url && (
                  <>
                    <span aria-hidden>·</span>
                    <a
                      href={deploy.pr_url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-0.5 underline-offset-4 hover:underline"
                    >
                      PR #{prNumber}
                      <ExternalLink className="size-3" aria-hidden />
                    </a>
                  </>
                )}
                <span aria-hidden>·</span>
                <span>{deploy.author ?? "—"}</span>
                <span aria-hidden>·</span>
                <span>{ago(deploy.registered_at)}</span>
                {lead != null && (
                  <>
                    <span aria-hidden>·</span>
                    <span title="merged → live">{formatDuration(lead)}</span>
                  </>
                )}
                <Badge
                  variant="outline"
                  className={
                    isLive
                      ? "text-[10px] font-normal text-emerald-600 dark:text-emerald-400"
                      : "text-[10px] font-normal text-muted-foreground"
                  }
                >
                  {isLive ? "live" : "not live"}
                </Badge>
              </div>
            </SheetHeader>

            <div className="flex flex-col gap-6 px-4 pb-4">
              {prNumber != null && deploy.pr_url && (
                <PrDescription
                  service={service}
                  prNumber={prNumber}
                  prUrl={deploy.pr_url}
                />
              )}

              <div className="flex flex-col gap-2">
                <SectionSubhead>Timeline</SectionSubhead>
                <DeployTimeline
                  service={service}
                  sha={deploy.sha ?? undefined}
                  revision={deploy.revision ?? undefined}
                  mergedAt={deploy.committed_at ?? undefined}
                />
              </div>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}

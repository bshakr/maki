import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowDownToLine,
  ExternalLink,
  KeyRound,
  RefreshCw,
  SearchX,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  fetchServiceLogs,
  isAwsCredentialsError,
  type LogEventItem,
  type ServiceLogsResponse,
} from "@/api";
import { AwsCredsError } from "@/components/aws-creds-error";
import { useConfig } from "@/components/config-provider";
import { cloudWatchLogsUrlForGroup, logGroupForService } from "@/lib/aws-console";
import { timestamp, timestampPrecise } from "@/lib/format";
import { cn } from "@/lib/utils";

const AUTO_REFRESH_MS = 5000;
const TAIL_LIMIT = 300;

// Highlight obviously-bad lines. ERROR/CRITICAL/FATAL pop destructive-red; WARN goes amber. Word
// boundaries so "ERRORS" still matches but "TERROR" inside a path doesn't catch a false WARN.
const ERROR_RE = /\b(error|critical|fatal|exception|traceback)\b/i;
const WARN_RE = /\b(warn|warning)\b/i;

function lineClass(message: string): string | undefined {
  if (ERROR_RE.test(message)) return "text-destructive";
  if (WARN_RE.test(message)) return "text-amber-600 dark:text-amber-400";
  return undefined;
}

function ConsoleLink({ url }: { url: string }) {
  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer"
      className="inline-flex w-fit items-center gap-1 text-xs font-medium text-primary hover:underline"
    >
      <ExternalLink className="size-3" aria-hidden />
      Open in AWS console
    </a>
  );
}

// A centred message + console-link fallback, shared by the not_found / forbidden / empty states.
function FallbackState({
  icon,
  title,
  detail,
  consoleUrl,
}: {
  icon: React.ReactNode;
  title: string;
  detail: string;
  consoleUrl: string;
}) {
  return (
    <div
      className="flex flex-1 flex-col items-center justify-center gap-3 px-6 py-12 text-center"
      data-testid="logs-fallback"
    >
      <span className="flex size-10 items-center justify-center rounded-lg bg-muted text-muted-foreground">
        {icon}
      </span>
      <div className="flex flex-col gap-1">
        <p className="text-sm font-medium text-foreground">{title}</p>
        <p className="max-w-sm text-xs text-muted-foreground">{detail}</p>
      </div>
      <ConsoleLink url={consoleUrl} />
    </div>
  );
}

function LogRows({ events }: { events: LogEventItem[] }) {
  const bottomRef = useRef<HTMLDivElement | null>(null);

  function jumpToLatest() {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }

  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <div
        data-testid="logs-scroll"
        className="min-h-0 flex-1 overflow-y-auto bg-muted/20 font-mono text-xs"
      >
        {/* Oldest at top, newest at bottom — reads like `tail -f`. */}
        {events.map((e, i) => (
          <div
            key={`${e.timestamp}:${i}`}
            className="flex gap-3 border-b border-border/40 px-4 py-1 last:border-b-0 hover:bg-muted/50"
          >
            <time
              dateTime={e.timestamp}
              title={`${timestampPrecise(e.timestamp)} · ${e.stream}`}
              className="shrink-0 tabular-nums text-muted-foreground"
            >
              {timestamp(e.timestamp)}
            </time>
            <span className={cn("min-w-0 break-words whitespace-pre-wrap", lineClass(e.message))}>
              {e.message}
            </span>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={jumpToLatest}
        className="absolute right-4 bottom-4 gap-1.5 shadow-sm"
      >
        <ArrowDownToLine className="size-3.5" aria-hidden />
        Jump to latest
      </Button>
    </div>
  );
}

function LogsSkeleton() {
  return (
    <div data-testid="logs-skeleton" className="flex flex-col gap-2 px-4 py-3">
      {Array.from({ length: 12 }).map((_, i) => (
        <Skeleton key={i} className="h-4" style={{ width: `${60 + ((i * 7) % 35)}%` }} />
      ))}
    </div>
  );
}

function LogsBody({
  data,
  isLoading,
  isError,
  error,
  consoleUrl,
  onRetry,
  retrying,
}: {
  data: ServiceLogsResponse | undefined;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  consoleUrl: string;
  onRetry: () => void;
  retrying: boolean;
}) {
  if (isError && isAwsCredentialsError(error)) {
    return (
      <div className="px-4 py-6">
        <AwsCredsError onRetry={onRetry} retrying={retrying} />
      </div>
    );
  }
  if (isError && !data) {
    return (
      <div
        role="alert"
        data-testid="logs-error"
        className="m-4 rounded-md border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive"
      >
        {error instanceof Error ? error.message : "Failed to load logs"}
      </div>
    );
  }
  if (isLoading && !data) {
    return <LogsSkeleton />;
  }
  if (!data) return null;

  if (data.error === "not_found") {
    return (
      <FallbackState
        icon={<SearchX className="size-5" aria-hidden />}
        title="No log group"
        detail={`No CloudWatch log group ${data.log_group} exists yet. Once the service has logged, it'll appear here.`}
        consoleUrl={consoleUrl}
      />
    );
  }
  if (data.error === "forbidden") {
    return (
      <FallbackState
        icon={<KeyRound className="size-5" aria-hidden />}
        title="maki can't read these logs"
        detail="maki's role lacks logs:FilterLogEvents for this group. Use the console link, or grant the permission."
        consoleUrl={consoleUrl}
      />
    );
  }
  if (data.events.length === 0) {
    return (
      <FallbackState
        icon={<SearchX className="size-5" aria-hidden />}
        title="No recent log events"
        detail="Nothing was logged in the recent window. Try refreshing, or widen the window in the console."
        consoleUrl={consoleUrl}
      />
    );
  }
  return <LogRows events={data.events} />;
}

export function LogsSheet({
  open,
  onOpenChange,
  service,
  consoleUrl,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  service: string;
  consoleUrl: string;
}) {
  const { aws_region, log_group_template } = useConfig();
  const [autoRefresh, setAutoRefresh] = useState(false);

  // Don't keep polling when the sheet is closed.
  useEffect(() => {
    if (!open) setAutoRefresh(false);
  }, [open]);

  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ["service-logs", service],
    queryFn: () => fetchServiceLogs(service, { limit: TAIL_LIMIT }),
    enabled: open,
    retry: (count, err) => !isAwsCredentialsError(err) && count < 1,
    refetchInterval: autoRefresh && open ? AUTO_REFRESH_MS : false,
  });

  // Once the backend has resolved the authoritative log group, build the console link from it
  // (the `/ecs/<service>-production` convention behind `consoleUrl` doesn't hold for every
  // service). Before the first response lands, fall back to the convention-based `consoleUrl`.
  const resolvedConsoleUrl = data?.log_group
    ? cloudWatchLogsUrlForGroup(data.log_group, data.region, aws_region)
    : consoleUrl;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        data-testid="logs-sheet"
        className="flex w-full flex-col gap-0 p-0 sm:max-w-2xl"
      >
        <SheetHeader className="gap-2 border-b px-4 pt-6 pb-4 pr-14">
          <SheetTitle className="flex items-center gap-2 text-base">
            <span>Logs · {service}</span>
            {data?.truncated && (
              <Badge variant="outline" className="text-[10px] font-normal text-muted-foreground">
                truncated
              </Badge>
            )}
          </SheetTitle>
          <SheetDescription className="font-mono text-xs">
            {/* The backend resolves and returns the authoritative group; only fall back to the
                shared convention helper before the first response lands. */}
            {data?.log_group ?? logGroupForService(service, log_group_template)}
          </SheetDescription>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => void refetch()}
              disabled={isFetching}
              className="gap-1.5"
            >
              <RefreshCw
                className={cn("size-3.5", isFetching && "animate-spin")}
                aria-hidden
              />
              Refresh
            </Button>
            <Button
              type="button"
              variant={autoRefresh ? "default" : "outline"}
              size="sm"
              onClick={() => setAutoRefresh((v) => !v)}
              aria-pressed={autoRefresh}
              className="gap-1.5"
            >
              <span
                className={cn(
                  "size-2 rounded-full",
                  autoRefresh ? "animate-pulse bg-current" : "bg-muted-foreground/50",
                )}
                aria-hidden
              />
              Auto-refresh {autoRefresh ? "on" : "off"}
            </Button>
            <a
              href={resolvedConsoleUrl}
              target="_blank"
              rel="noreferrer"
              className="ml-auto inline-flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground hover:underline"
            >
              <ExternalLink className="size-3" aria-hidden />
              Console
            </a>
          </div>
        </SheetHeader>

        <LogsBody
          data={data}
          isLoading={isLoading}
          isError={isError}
          error={error}
          consoleUrl={resolvedConsoleUrl}
          onRetry={() => void refetch()}
          retrying={isFetching}
        />
      </SheetContent>
    </Sheet>
  );
}

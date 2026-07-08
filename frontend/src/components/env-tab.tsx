import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, Copy, Eye, EyeOff } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchServiceEnv, type ContainerEnv, type ServiceEnvResponse } from "@/api";

function CopyButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);

  function copy() {
    void navigator.clipboard.writeText(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-xs"
      className="shrink-0"
      onClick={copy}
      aria-label={label}
    >
      {copied ? (
        <Check className="size-3.5" aria-hidden />
      ) : (
        <Copy className="size-3.5" aria-hidden />
      )}
    </Button>
  );
}

// Env values can be plaintext secrets (passwords, tokens), so they're masked by default —
// reveal per-row with the eye, copy with the copy button. A fixed-width dot run avoids leaking
// the value's length.
function MaskedValue({ value }: { value: string | null }) {
  const [shown, setShown] = useState(false);

  if (value == null) {
    return <span className="font-mono text-sm text-muted-foreground">—</span>;
  }
  return (
    <span className="flex min-w-0 items-center gap-1.5">
      <span className="truncate font-mono text-sm">{shown ? value : "••••••••"}</span>
      <Button
        type="button"
        variant="ghost"
        size="icon-xs"
        className="shrink-0"
        onClick={() => setShown((s) => !s)}
        aria-label={shown ? "Hide value" : "Reveal value"}
        aria-pressed={shown}
      >
        {shown ? (
          <EyeOff className="size-3.5" aria-hidden />
        ) : (
          <Eye className="size-3.5" aria-hidden />
        )}
      </Button>
      <CopyButton value={value} label="Copy value" />
    </span>
  );
}

// Deep-link a secret's SSM-parameter ARN to its AWS console page, so the VALUE is resolved in
// AWS (IAM-gated, CloudTrail-audited) rather than ever by maki. Non-SSM refs get no link.
function ssmConsoleUrl(valueFrom: string): string | null {
  const m = valueFrom.match(/^arn:aws:ssm:([^:]+):[^:]+:parameter(\/.+)$/);
  if (!m) return null;
  const [, region, name] = m;
  return `https://${region}.console.aws.amazon.com/systems-manager/parameters/${encodeURIComponent(
    name,
  )}/description?region=${region}`;
}

function ContainerSection({
  container,
  showName,
}: {
  container: ContainerEnv;
  showName: boolean;
}) {
  return (
    <Card data-testid="env-container">
      <CardHeader>
        <CardTitle className="text-sm font-medium">
          {showName ? (
            <span className="font-mono">{container.name}</span>
          ) : (
            <span className="text-muted-foreground">Configuration</span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        <section>
          <h3 className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
            Environment
          </h3>
          {container.environment.length === 0 ? (
            <div className="text-sm text-muted-foreground">
              No environment variables.
            </div>
          ) : (
            <dl className="flex flex-col divide-y">
              {container.environment.map((e, i) => (
                <div
                  key={`${e.name}:${i}`}
                  className="flex flex-col gap-0.5 py-1.5 sm:flex-row sm:gap-3"
                >
                  <dt className="font-mono text-sm text-muted-foreground sm:w-1/3 sm:shrink-0">
                    {e.name}
                  </dt>
                  <dd className="min-w-0">
                    <MaskedValue value={e.value} />
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </section>

        <section>
          <h3 className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
            Secrets
          </h3>
          {container.secrets.length === 0 ? (
            <div className="text-sm text-muted-foreground">No secrets.</div>
          ) : (
            <dl className="flex flex-col divide-y">
              {container.secrets.map((s, i) => (
                <div
                  key={`${s.name}:${i}`}
                  className="flex flex-col gap-0.5 py-1.5 sm:flex-row sm:items-center sm:gap-3"
                >
                  <dt className="font-mono text-sm text-muted-foreground sm:w-1/3 sm:shrink-0">
                    {s.name}
                  </dt>
                  <dd className="flex min-w-0 items-center gap-1.5">
                    {ssmConsoleUrl(s.value_from) ? (
                      <a
                        href={ssmConsoleUrl(s.value_from)!}
                        target="_blank"
                        rel="noreferrer"
                        className="truncate font-mono text-sm underline-offset-4 hover:underline"
                        title={`${s.value_from} — open in AWS console`}
                      >
                        {s.value_from}
                      </a>
                    ) : (
                      <span
                        className="truncate font-mono text-sm"
                        title={s.value_from}
                      >
                        {s.value_from}
                      </span>
                    )}
                    <CopyButton value={s.value_from} label="Copy secret reference" />
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </section>
      </CardContent>
    </Card>
  );
}

function EnvTabSkeleton() {
  return (
    <div data-testid="env-tab" className="flex flex-col gap-4">
      <Skeleton className="h-6 w-48" />
      <Card>
        <CardHeader>
          <Skeleton className="h-4 w-32" />
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Skeleton className="h-5 w-full" />
          <Skeleton className="h-5 w-full" />
          <Skeleton className="h-5 w-2/3" />
        </CardContent>
      </Card>
    </div>
  );
}

function isEmpty(data: ServiceEnvResponse): boolean {
  return data.containers.every(
    (c) => c.environment.length === 0 && c.secrets.length === 0,
  );
}

export function EnvTab({ service }: { service: string }) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["service-env", service],
    queryFn: () => fetchServiceEnv(service),
  });

  if (isLoading && !data) {
    return <EnvTabSkeleton />;
  }

  if (isError && !data) {
    return (
      <div
        data-testid="env-tab"
        role="alert"
        className="rounded-md border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive"
      >
        {error instanceof Error ? error.message : "Failed to load env"}
      </div>
    );
  }

  if (!data) return null;

  const multi = data.containers.length > 1;

  return (
    <div data-testid="env-tab" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs text-muted-foreground">
          task def:{" "}
          <span className="font-mono text-foreground">
            {data.task_def ?? "—"}
          </span>
        </span>
        <Badge variant="outline" className="text-muted-foreground">
          Read-only
        </Badge>
      </div>

      {isEmpty(data) ? (
        <Card>
          <CardContent className="flex h-40 items-center justify-center text-sm text-muted-foreground">
            No environment configured.
          </CardContent>
        </Card>
      ) : (
        data.containers.map((container) => (
          <ContainerSection
            key={container.name}
            container={container}
            showName={multi}
          />
        ))
      )}
    </div>
  );
}

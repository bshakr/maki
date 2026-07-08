import { KeyRound, RefreshCw, Terminal } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

// ─────────────────────────────────────────────────────────────────────────────
// AWS creds gone — the friendly stop-the-world state. maki reads LIVE AWS as the
// operator's assumed (SSO) identity; when that lapses, every API call 503s. This
// panel explains exactly how to recover (re-assume + restart the backend in the
// SAME shell) instead of leaving a generic "failed to load" error. Uses the Nory
// Card + tokens so it's theme-aware (light/dark) by construction.
// ─────────────────────────────────────────────────────────────────────────────

function Step({ n, children }: { n: number; children: React.ReactNode }) {
  return (
    <li className="flex gap-3">
      <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-muted text-[11px] font-semibold tabular-nums text-muted-foreground">
        {n}
      </span>
      <span className="text-sm leading-relaxed text-muted-foreground">{children}</span>
    </li>
  );
}

function Code({ children }: { children: React.ReactNode }) {
  return (
    <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[0.8125rem] text-foreground">
      {children}
    </code>
  );
}

export function AwsCredsError({
  onRetry,
  retrying,
}: {
  onRetry?: () => void;
  retrying?: boolean;
}) {
  return (
    <Card role="alert" className="mx-auto max-w-xl border-amber-500/40">
      <CardHeader className="flex flex-row items-center gap-3 space-y-0">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-amber-500/10 text-amber-600 dark:text-amber-400">
          <KeyRound className="size-5" aria-hidden />
        </span>
        <div className="grid gap-0.5">
          <CardTitle>AWS credentials missing or expired</CardTitle>
          <p className="text-sm text-muted-foreground">
            maki reads live AWS as your assumed identity — that session has lapsed.
          </p>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <ol className="flex flex-col gap-3">
          <Step n={1}>
            In the shell where you started the backend, re-run <Code>assume</Code> and pick the
            prod profile.
          </Step>
          <Step n={2}>
            Restart the backend <em>in that same shell</em> so it inherits the fresh credentials
            (from <Code>backend/</Code>, with the venv active):
            <span className="mt-1.5 flex items-center gap-2 rounded-md border bg-muted/40 px-2.5 py-1.5 font-mono text-[0.8125rem]">
              <Terminal className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
              source .venv/bin/activate &amp;&amp; uvicorn maki.api:app --port 8787
            </span>
          </Step>
          <Step n={3}>Once it's back up, retry below — the dashboard will reload.</Step>
        </ol>

        {onRetry && (
          <div className="flex justify-end">
            <Button variant="outline" size="sm" onClick={onRetry} disabled={retrying}>
              <RefreshCw
                className={retrying ? "size-3.5 animate-spin" : "size-3.5"}
                aria-hidden
              />
              Retry
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

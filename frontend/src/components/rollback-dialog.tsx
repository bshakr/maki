import { useEffect, useState } from "react";
import { AlertTriangle, ExternalLink, Info } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  previewRollback,
  type DeployRecord,
  type RollbackPreview,
} from "@/api";
import { shortSha } from "@/lib/format";

export function RollbackDialog({
  open,
  onOpenChange,
  service,
  currentSha,
  target,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  service: string;
  currentSha: string | null;
  target: DeployRecord | null;
}) {
  const [confirmName, setConfirmName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RollbackPreview | null>(null);

  // Reset transient state each time the dialog (re)opens.
  useEffect(() => {
    if (open) {
      setConfirmName("");
      setSubmitting(false);
      setError(null);
      setResult(null);
    }
  }, [open]);

  const nameMatches = confirmName === service;
  const canPreview = nameMatches && !!target?.sha && !submitting;

  const prSegment = target?.pr_url?.split("/").pop();
  const prNumber = prSegment && /^\d+$/.test(prSegment) ? ` #${prSegment}` : "";

  async function handlePreview() {
    if (!canPreview || !target?.sha) return;
    setSubmitting(true);
    setError(null);
    try {
      const preview = await previewRollback(service, target.sha);
      setResult(preview);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Rollback preview failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="rollback-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <span>Roll back {service}</span>
            <Badge variant="secondary">PREVIEW</Badge>
          </DialogTitle>
          <DialogDescription>
            Inspect what a rollback would target. Nothing is executed.
          </DialogDescription>
        </DialogHeader>

        <Alert variant="destructive">
          <AlertTriangle className="size-4" aria-hidden />
          <AlertTitle>Preview only</AlertTitle>
          <AlertDescription>
            This does not change production — execution is intentionally not
            implemented.
          </AlertDescription>
        </Alert>

        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label className="text-sm text-muted-foreground">Roll back to</label>
            {target?.sha ? (
              <div
                data-testid="rollback-target"
                className="rounded-md border bg-muted/40 px-3 py-2.5"
              >
                <p className="text-sm font-medium leading-snug text-foreground">
                  {target.message ?? "—"}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  <span className="font-mono">{shortSha(target.sha)}</span>
                  {target.revision != null ? ` · rev ${target.revision}` : ""}
                  {target.author ? ` · ${target.author}` : ""}
                </p>
                {target.pr_url && (
                  <a
                    href={target.pr_url}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
                  >
                    <ExternalLink className="size-3" aria-hidden />
                    PR{prNumber}
                  </a>
                )}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                No deployment selected to roll back to.
              </p>
            )}
            {currentSha && (
              <p className="text-xs text-muted-foreground">
                Replacing current{" "}
                <span className="font-mono">{shortSha(currentSha)}</span>
              </p>
            )}
          </div>

          <div className="flex flex-col gap-1.5">
            <label htmlFor="rollback-confirm" className="text-sm text-muted-foreground">
              Type{" "}
              <span className="font-mono font-semibold text-foreground">
                {service}
              </span>{" "}
              to confirm
            </label>
            <Input
              id="rollback-confirm"
              value={confirmName}
              onChange={(e) => setConfirmName(e.target.value)}
              placeholder={service}
              autoComplete="off"
            />
          </div>

          {error && (
            <Alert variant="destructive">
              <AlertTitle>Preview failed</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {result && (
            <Alert data-testid="rollback-result">
              <Info className="size-4" aria-hidden />
              <AlertTitle>Preview only — no production change was made.</AlertTitle>
              <AlertDescription>{result.message}</AlertDescription>
            </Alert>
          )}
        </div>

        <DialogFooter>
          <Button
            onClick={handlePreview}
            disabled={!canPreview}
            title={
              nameMatches
                ? undefined
                : `Type "${service}" to enable the preview`
            }
          >
            {submitting ? "Previewing…" : "Preview rollback"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

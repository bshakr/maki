import { useEffect, useState } from "react";
import { AlertTriangle, Info } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { runTaskPreview, type RunTaskPreview } from "@/api";

export function RunTaskSheet({
  open,
  onOpenChange,
  service,
  taskDef,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  service: string;
  taskDef: string | null;
}) {
  const [command, setCommand] = useState("");
  const [confirmName, setConfirmName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RunTaskPreview | null>(null);

  // Reset transient state each time the sheet (re)opens.
  useEffect(() => {
    if (open) {
      setCommand("");
      setConfirmName("");
      setSubmitting(false);
      setError(null);
      setResult(null);
    }
  }, [open]);

  const nameMatches = confirmName === service;
  const commandFilled = command.trim().length > 0;
  const canPreview = nameMatches && commandFilled && !submitting;

  async function handlePreview() {
    if (!canPreview) return;
    setSubmitting(true);
    setError(null);
    try {
      const preview = await runTaskPreview(service, command, taskDef);
      setResult(preview);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Run-task preview failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent data-testid="run-task-sheet" className="sm:max-w-md">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            <span>Run task · {service}</span>
            <Badge variant="secondary">PREVIEW</Badge>
          </SheetTitle>
          <SheetDescription>
            Inspect what a one-off task run would do. Nothing is executed.
          </SheetDescription>
        </SheetHeader>

        <div className="flex flex-col gap-4 px-4">
          <Alert variant="destructive">
            <AlertTriangle className="size-4" aria-hidden />
            <AlertTitle>Preview only</AlertTitle>
            <AlertDescription>
              Execution is intentionally not implemented. Nothing runs in
              production.
            </AlertDescription>
          </Alert>

          <div className="flex flex-col gap-1.5">
            <label htmlFor="run-task-command" className="text-sm text-muted-foreground">
              Command
            </label>
            <Textarea
              id="run-task-command"
              value={command}
              onChange={(e) => setCommand(e.target.value)}
              placeholder="python -m scripts.backfill --since 2026-05-01"
              className="font-mono"
              rows={3}
              autoComplete="off"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-sm text-muted-foreground">Task definition</label>
            <p className="font-mono text-sm text-muted-foreground">
              {taskDef ?? "current"}
            </p>
          </div>

          <div className="flex flex-col gap-1.5">
            <label htmlFor="run-task-confirm" className="text-sm text-muted-foreground">
              Type{" "}
              <span className="font-mono font-semibold text-foreground">
                {service}
              </span>{" "}
              to confirm
            </label>
            <Input
              id="run-task-confirm"
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
            <Alert data-testid="run-task-result">
              <Info className="size-4" aria-hidden />
              <AlertTitle>Preview only — no production change was made.</AlertTitle>
              <AlertDescription>{result.message}</AlertDescription>
            </Alert>
          )}
        </div>

        <SheetFooter>
          <Button
            onClick={handlePreview}
            disabled={!canPreview}
            title={
              canPreview
                ? undefined
                : `Type "${service}" and enter a command to enable the preview`
            }
          >
            {submitting ? "Previewing…" : "Preview run"}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

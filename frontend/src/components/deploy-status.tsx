import { CircleCheck, RotateCcw, TriangleAlert } from "lucide-react";

import { Badge } from "@/components/ui/badge";

// Visual treatment per deploy outcome. Rollback wins (the thing you most need to
// spot during an incident), then a failed rollout, then a live one; a plain
// success stays quiet so the exceptions are what pop while scanning.
//
// Shared by the fleet-wide activity card and the service-page history rows so the
// rollback/failed/live/success treatments come from ONE source of truth.
export type DeployState =
  | "rollback"
  | "failed"
  | "in_progress"
  | "success"
  | "none";

// The minimal shape both call sites already carry; keeps this module decoupled
// from the richer ActivityItem / DeployRecord types.
export interface DeployStatusFields {
  status: "in_progress" | "success" | "failed" | null;
  is_rollback: boolean;
}

export function deployState(item: DeployStatusFields): DeployState {
  if (item.is_rollback) return "rollback";
  if (item.status === "failed") return "failed";
  if (item.status === "in_progress") return "in_progress";
  if (item.status === "success") return "success";
  return "none";
}

// Coloured edge for the states worth catching; neutral border otherwise.
export const STATE_BORDER: Record<DeployState, string> = {
  rollback: "border-orange-600/50",
  failed: "border-destructive/50",
  in_progress: "border-primary/50",
  success: "",
  none: "",
};

// A pulsing dot for an in-flight rollout, tinted to its container's text colour.
export function LiveDot() {
  return (
    <span className="relative flex size-2" aria-hidden>
      <span className="absolute inline-flex size-full animate-ping rounded-full bg-current opacity-75" />
      <span className="relative inline-flex size-2 rounded-full bg-current" />
    </span>
  );
}

export function StatusMarker({ state }: { state: DeployState }) {
  switch (state) {
    case "rollback":
      return (
        <Badge variant="warning" className="gap-1">
          <RotateCcw className="size-3" aria-hidden />
          rollback
        </Badge>
      );
    case "failed":
      return (
        <Badge variant="destructive" className="gap-1">
          <TriangleAlert className="size-3" aria-hidden />
          failed
        </Badge>
      );
    case "in_progress":
      return (
        <Badge variant="default" className="gap-1.5">
          <LiveDot />
          deploying
        </Badge>
      );
    case "success":
      return (
        <CircleCheck
          className="size-4 text-green-600 dark:text-green-500"
          aria-label="succeeded"
        />
      );
    default:
      return null;
  }
}

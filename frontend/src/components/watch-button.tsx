import * as React from "react";
import { Bell, BellRing } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { addWatch, fetchWatches, removeWatch } from "@/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// Sibling of PinButton, but a different thing: a pin is personal and local (it reorders the
// board), a watch is server-side and makes this service's deploys raise a desktop notification.
// Pressed state is read back from the server, so a failed write leaves the button telling the
// truth rather than flipping optimistically.
export function WatchButton({
  name,
  size = "icon-sm",
  withLabel = false,
  stopPropagation = true,
  className,
  ...props
}: {
  name: string;
  size?: React.ComponentProps<typeof Button>["size"];
  withLabel?: boolean;
  stopPropagation?: boolean;
} & Omit<
  React.ComponentProps<typeof Button>,
  "size" | "onClick" | "children"
>) {
  const queryClient = useQueryClient();
  const { data } = useQuery({ queryKey: ["watches"], queryFn: fetchWatches });
  const watched = (data?.watches ?? []).some((w) => w.service === name);

  const toggle = useMutation({
    mutationFn: async () => {
      if (watched) await removeWatch(name);
      else await addWatch(name);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["watches"] }),
  });

  const Icon = watched ? BellRing : Bell;
  const title = toggle.isError
    ? "Couldn't update notifications — try again"
    : watched
      ? "Notifying on deploys"
      : "Notify me on deploys";

  return (
    <Button
      type="button"
      variant={withLabel ? "outline" : "ghost"}
      size={withLabel ? "sm" : size}
      aria-pressed={watched}
      // WCAG 2.5.3: an aria-label that doesn't contain the visible text leaves voice control
      // with nothing to match when someone says "click Watch".
      aria-label={
        withLabel
          ? undefined
          : watched
            ? `Stop notifying me about ${name} deploys`
            : `Notify me about ${name} deploys`
      }
      title={title}
      aria-busy={toggle.isPending}
      onClick={(e) => {
        if (stopPropagation) e.stopPropagation();
        // Guard rather than `disabled`: disabling the focused button blurs it, and the write plus
        // its refetch is long enough to lose the operator's place on a hover-revealed control.
        if (toggle.isPending) return;
        toggle.mutate();
      }}
      onKeyDown={(e) => {
        // Cards bind Enter/Space to navigate — keep those keys local to the
        // button when it's nested inside one.
        if (stopPropagation && (e.key === "Enter" || e.key === " ")) {
          e.stopPropagation();
        }
      }}
      className={cn(
        toggle.isError
          ? "text-destructive"
          : watched
            ? "text-amber-600 hover:text-amber-600 dark:text-amber-400 dark:hover:text-amber-400"
            : "text-muted-foreground",
        className,
      )}
      {...props}
    >
      <Icon className={watched ? "fill-current" : undefined} aria-hidden />
      {withLabel ? (watched ? "Watching" : "Watch") : null}
    </Button>
  );
}

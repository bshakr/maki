import * as React from "react";
import { Pin } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { usePins } from "@/lib/pins";

// A small toggle that pins/unpins a single service. Filled + violet when pinned,
// muted outline when not. Often lives inside a clickable card/link, so it stops
// click + keyboard propagation by default to avoid triggering the parent.
export function PinButton({
  name,
  size = "icon-sm",
  className,
  stopPropagation = true,
  ...props
}: {
  name: string;
  size?: React.ComponentProps<typeof Button>["size"];
  stopPropagation?: boolean;
} & Omit<
  React.ComponentProps<typeof Button>,
  "size" | "onClick" | "children"
>) {
  const { isPinned, toggle } = usePins();
  const pinned = isPinned(name);

  return (
    <Button
      type="button"
      variant="ghost"
      size={size}
      aria-pressed={pinned}
      aria-label={pinned ? `Unpin ${name}` : `Pin ${name}`}
      title={pinned ? "Unpin" : "Pin"}
      onClick={(e) => {
        if (stopPropagation) e.stopPropagation();
        toggle(name);
      }}
      onKeyDown={(e) => {
        // Cards bind Enter/Space to navigate — keep those keys local to the
        // button when it's nested inside one.
        if (stopPropagation && (e.key === "Enter" || e.key === " ")) {
          e.stopPropagation();
        }
      }}
      className={cn(
        pinned
          ? "text-violet-600 hover:text-violet-600 dark:text-violet-400 dark:hover:text-violet-400"
          : "text-muted-foreground",
        className,
      )}
      {...props}
    >
      <Pin className={pinned ? "fill-current" : undefined} aria-hidden />
    </Button>
  );
}

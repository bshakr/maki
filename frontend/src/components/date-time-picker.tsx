import * as React from "react";
import { CalendarIcon, Crosshair } from "lucide-react";
import { format } from "date-fns";

import { buttonVariants } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Input } from "@/components/ui/input";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { toLocalInput } from "@/lib/format";
import { cn } from "@/lib/utils";

// The control speaks the same local "YYYY-MM-DDTHH:mm" string the native datetime-local input did,
// so callers stay timezone-naive (local) and the jump logic upstream is unchanged — we just swap
// the browser chrome for a Nory-themed Calendar + time field in a popover.
export function DateTimePicker({
  value,
  onChange,
  onJump,
  className,
}: {
  /** Local datetime as "YYYY-MM-DDTHH:mm". */
  value: string;
  onChange: (next: string) => void;
  /** Commit the picked moment. When provided, a Jump button renders in the popover. */
  onJump?: () => void;
  className?: string;
}) {
  const [open, setOpen] = React.useState(false);

  const date = React.useMemo(() => {
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? new Date() : d;
  }, [value]);

  const time = format(date, "HH:mm");

  // Keep the time-of-day when the day changes, and the day when time changes.
  function setDay(next?: Date) {
    if (!next) return;
    const merged = new Date(next);
    merged.setHours(date.getHours(), date.getMinutes(), 0, 0);
    onChange(toLocalInput(merged));
  }

  function setTime(t: string) {
    const [h, m] = t.split(":").map(Number);
    if (Number.isNaN(h) || Number.isNaN(m)) return;
    const merged = new Date(date);
    merged.setHours(h, m, 0, 0);
    onChange(toLocalInput(merged));
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        {/* Native <button>, not the function-component Button: radix Slot must
            forward a ref to the trigger for Popper to anchor the popover. A DOM
            element always accepts that ref (Button only does on React 19+), so
            this keeps the popover positioned correctly regardless of version. */}
        <button
          type="button"
          aria-label="Jump to timestamp"
          data-testid="datetime-trigger"
          className={cn(
            buttonVariants({ variant: "outline" }),
            "w-[15rem] justify-start gap-2 font-normal",
            className,
          )}
        >
          <CalendarIcon className="size-4 text-muted-foreground" aria-hidden />
          {format(date, "MMM d, yyyy")}
          <span className="text-muted-foreground" aria-hidden>
            ·
          </span>
          <span className="tabular-nums">{time}</span>
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-auto p-0">
        <Calendar mode="single" selected={date} onSelect={setDay} autoFocus />
        <div className="flex items-center gap-2 border-t p-3">
          <span className="text-xs text-muted-foreground">Time</span>
          <Input
            type="time"
            aria-label="Time"
            value={time}
            onChange={(e) => setTime(e.target.value)}
            className="w-[7.5rem] [accent-color:var(--primary)]"
          />
          {onJump && (
            <button
              type="button"
              data-testid="datetime-jump"
              className={cn(buttonVariants({ size: "sm" }), "ml-auto gap-1.5")}
              onClick={() => {
                onJump();
                setOpen(false);
              }}
            >
              <Crosshair className="size-3.5" aria-hidden />
              Jump
            </button>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}

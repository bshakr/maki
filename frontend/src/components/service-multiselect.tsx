import * as React from "react";
import { Check, ChevronsUpDown, ListFilter, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";

// A Nory-themed, searchable, multiple-choice service filter built from the
// shadcn Popover + Command (cmdk) primitives — the canonical combobox-multiselect
// pattern. The trigger mirrors the date-time-picker's outline styling so the two
// controls in the Activity header read as one cohesive set.
export function ServiceMultiSelect({
  options,
  selected,
  onChange,
  className,
}: {
  /** Every selectable service name (already de-duped + sorted by the caller). */
  options: string[];
  /** Currently-selected service names. */
  selected: string[];
  onChange: (next: string[]) => void;
  className?: string;
}) {
  const [open, setOpen] = React.useState(false);

  const selectedSet = React.useMemo(() => new Set(selected), [selected]);

  function toggle(service: string) {
    const next = new Set(selectedSet);
    if (next.has(service)) next.delete(service);
    else next.add(service);
    onChange([...next]);
  }

  function clear() {
    onChange([]);
  }

  // Trigger label: "All services" (none), the single name (one), or "<N> services".
  const label =
    selected.length === 0
      ? "All services"
      : selected.length === 1
        ? selected[0]
        : `${selected.length} services`;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        {/* Native <button> (not the Button component) so radix Slot can forward
            the ref Popper needs to anchor the popover — matches DateTimePicker. */}
        <button
          type="button"
          aria-label="Filter by service"
          aria-expanded={open}
          data-testid="service-filter-trigger"
          className={cn(
            buttonVariants({ variant: "outline" }),
            "min-w-[12rem] justify-start gap-2 font-normal",
            className,
          )}
        >
          <ListFilter className="size-4 text-muted-foreground" aria-hidden />
          <span className="truncate">{label}</span>
          {selected.length > 0 && (
            <Badge
              variant="secondary"
              className="ml-1 h-5 px-1.5 tabular-nums"
              aria-hidden
            >
              {selected.length}
            </Badge>
          )}
          <ChevronsUpDown
            className="ml-auto size-4 shrink-0 text-muted-foreground"
            aria-hidden
          />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[16rem] p-0">
        <Command>
          <CommandInput placeholder="Search services…" />
          <CommandList>
            <CommandEmpty>No services found.</CommandEmpty>
            <CommandGroup>
              {options.map((service) => {
                const isSelected = selectedSet.has(service);
                return (
                  <CommandItem
                    key={service}
                    value={service}
                    onSelect={() => toggle(service)}
                    className="gap-2"
                    aria-selected={isSelected}
                  >
                    <span
                      className={cn(
                        "flex size-4 shrink-0 items-center justify-center rounded-[4px] border border-primary",
                        isSelected
                          ? "bg-primary text-primary-foreground"
                          : "opacity-60 [&_svg]:invisible",
                      )}
                    >
                      <Check className="size-3" aria-hidden />
                    </span>
                    <span className="truncate">{service}</span>
                  </CommandItem>
                );
              })}
            </CommandGroup>
            {selected.length > 0 && (
              <>
                <CommandSeparator />
                <CommandGroup>
                  <CommandItem
                    onSelect={clear}
                    className="justify-center text-center text-muted-foreground"
                  >
                    <X className="size-3.5" aria-hidden />
                    Clear filter
                  </CommandItem>
                </CommandGroup>
              </>
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

import { useQuery } from "@tanstack/react-query"
import { CircleArrowUp } from "lucide-react"

import { fetchVersion } from "@/api"
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar"

// Quiet "your clone is behind" affordance for long-running dev sessions: `make dev` can stay
// up for days, so a launch-time terminal nudge alone goes stale. Hidden entirely when up to
// date or when the check couldn't run (offline, not a repo) — absence of signal is silence.
export function UpdateBadge() {
  const { data } = useQuery({
    queryKey: ["version"],
    queryFn: fetchVersion,
    // Backend re-checks the remote hourly at most; poll well under that without hammering.
    refetchInterval: 15 * 60_000,
    // Match the poll interval so window-focus refetches don't bypass the 15-min cadence.
    staleTime: 15 * 60_000,
    retry: false,
  })

  if (!data?.update_available) return null

  const detail = data.behind_by
    ? `${data.behind_by} commit${data.behind_by === 1 ? "" : "s"} behind`
    : "new version available"

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <SidebarMenuButton
          tooltip="Run `make update` to get the latest"
          className="text-amber-600 dark:text-amber-500"
        >
          <CircleArrowUp />
          <div className="grid flex-1 text-left leading-tight group-data-[collapsible=icon]:hidden">
            <span className="truncate text-sm font-medium">Update available</span>
            <span className="truncate text-xs text-muted-foreground">
              {detail} — make update
            </span>
          </div>
        </SidebarMenuButton>
      </SidebarMenuItem>
    </SidebarMenu>
  )
}

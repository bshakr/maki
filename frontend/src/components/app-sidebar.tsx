import * as React from "react"
import {
  Activity,
  BarChart3,
  LayoutGrid,
  type LucideIcon,
} from "lucide-react"
import { Link } from "react-router-dom"

import { useConfig } from "@/components/config-provider"
import { MarkLogo } from "@/components/logo"
import { NavMain } from "@/components/nav-main"
import { NavPins } from "@/components/nav-pins"
import { NavUser } from "@/components/nav-user"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  SidebarTrigger,
} from "@/components/ui/sidebar"

type NavItem = {
  title: string
  url: string
  icon: LucideIcon
  iconClassName?: string
}

// A touch of colour per section so the nav scans at a glance (kept on -500
// shades that read on both the light and dark sidebar).
const navMain: NavItem[] = [
  { title: "Services", url: "/", icon: LayoutGrid, iconClassName: "text-violet-500" },
  { title: "Activity", url: "/activity", icon: Activity, iconClassName: "text-sky-500" },
  { title: "Metrics", url: "/metrics", icon: BarChart3, iconClassName: "text-emerald-500" },
]

export function AppSidebar({ ...props }: React.ComponentProps<typeof Sidebar>) {
  const { app_name } = useConfig()
  return (
    <Sidebar variant="inset" collapsible="icon" {...props}>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem className="flex flex-row items-center justify-between gap-1 group-data-[collapsible=icon]:flex-col group-data-[collapsible=icon]:gap-1">
            <SidebarMenuButton size="lg" asChild tooltip={app_name} className="flex-1">
              <Link to="/">
                <MarkLogo className="size-6 shrink-0 text-primary" />
                {/* Collapsed (icon mode) shows the mark only — hide the wordmark. */}
                <span className="text-base font-semibold group-data-[collapsible=icon]:hidden">
                  {app_name}
                </span>
              </Link>
            </SidebarMenuButton>
            {/* Expanded: collapse toggle next to the wordmark. */}
            <SidebarTrigger className="size-8 shrink-0 text-muted-foreground group-data-[collapsible=icon]:hidden" />
            {/* Collapsed: expand toggle below the mark — always a visible affordance. */}
            <SidebarTrigger className="hidden size-8 shrink-0 text-muted-foreground group-data-[collapsible=icon]:flex" />
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <NavMain items={navMain} />
        <NavPins />
      </SidebarContent>
      <SidebarFooter>
        <NavUser />
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}

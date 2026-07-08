import { useQuery } from "@tanstack/react-query"
import { BadgeCheck, ChevronsUpDown, LogOut } from "lucide-react"

import { fetchIdentity, isAwsCredentialsError, type IdentityResponse } from "@/api"
import { useConfig } from "@/components/config-provider"
import { ThemeToggle } from "@/components/theme-toggle"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar"

// The sidebar account block reflects the ASSUMED AWS identity behind the backend
// (sts:GetCallerIdentity), not a hardcoded user. When creds are absent/expired the
// /api/identity call 503s → we degrade to a neutral "No AWS identity" label rather
// than showing stale or fake details.

type IdentityView = {
  name: string
  detail: string
  initials: string
}

const NO_IDENTITY: IdentityView = {
  name: "No AWS identity",
  detail: "Run `assume`",
  initials: "—",
}

// Initials from a role/session name: split on non-alphanumerics ("bob.smith"
// → "BS"), fall back to the first two letters of a single token.
function initialsFrom(name: string): string {
  const parts = name.split(/[^a-zA-Z0-9]+/).filter(Boolean)
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return "?"
}

function toView(identity: IdentityResponse | undefined): IdentityView {
  const name = identity?.name?.trim()
  if (!name) return NO_IDENTITY
  const detail = identity?.account ? `account ${identity.account}` : "AWS"
  return { name, detail, initials: initialsFrom(name) }
}

export function NavUser() {
  const { isMobile } = useSidebar()
  const { env_label: envLabel } = useConfig()

  const { data, error } = useQuery({
    queryKey: ["identity"],
    queryFn: fetchIdentity,
    // A creds failure is an expected, recoverable state — don't hammer STS retrying it.
    retry: (count, err) => !isAwsCredentialsError(err) && count < 1,
    refetchInterval: 15_000,
  })

  const view = error ? NO_IDENTITY : toView(data)

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <div className="flex items-center justify-between gap-2 px-1 group-data-[collapsible=icon]:flex-col group-data-[collapsible=icon]:px-0">
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground group-data-[collapsible=icon]:hidden">
            <span className="size-2 rounded-full bg-emerald-500" />
            {envLabel}
          </span>
          <ThemeToggle />
        </div>
      </SidebarMenuItem>

      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuButton
              size="lg"
              tooltip="Account"
              className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
            >
              <Avatar className="h-8 w-8 rounded-lg">
                <AvatarFallback className="rounded-lg">
                  {view.initials}
                </AvatarFallback>
              </Avatar>
              <div className="grid flex-1 text-left text-sm leading-tight">
                <span className="truncate font-medium">{view.name}</span>
                <span className="truncate text-xs text-muted-foreground">
                  {view.detail}
                </span>
              </div>
              <ChevronsUpDown className="ml-auto size-4" />
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            className="w-(--radix-dropdown-menu-trigger-width) min-w-56 rounded-lg"
            side={isMobile ? "bottom" : "right"}
            align="end"
            sideOffset={4}
          >
            <DropdownMenuLabel className="p-0 font-normal">
              <div className="flex items-center gap-2 px-1 py-1.5 text-left text-sm">
                <Avatar className="h-8 w-8 rounded-lg">
                  <AvatarFallback className="rounded-lg">
                    {view.initials}
                  </AvatarFallback>
                </Avatar>
                <div className="grid flex-1 text-left text-sm leading-tight">
                  <span className="truncate font-medium">{view.name}</span>
                  <span className="truncate text-xs text-muted-foreground">
                    {view.detail}
                  </span>
                </div>
              </div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuGroup>
              <DropdownMenuItem disabled>
                <BadgeCheck />
                Account
              </DropdownMenuItem>
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
            <DropdownMenuItem disabled>
              <LogOut />
              Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  )
}

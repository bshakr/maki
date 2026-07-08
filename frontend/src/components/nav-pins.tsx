import { Pin, X } from "lucide-react";
import { Link, useLocation } from "react-router-dom";

import {
  SidebarGroup,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { usePins } from "@/lib/pins";

// "Pins" sidebar section — the services the user cares about, linking straight
// to each detail page. Hidden entirely when there are no pins (no empty box).
// Collapsed/icon mode hides labels + the unpin action like the rest of the nav.
export function NavPins() {
  const { pins, unpin } = usePins();
  const { pathname } = useLocation();

  if (pins.length === 0) return null;

  return (
    <SidebarGroup>
      <SidebarGroupLabel>Pins</SidebarGroupLabel>
      <nav aria-label="Pinned services">
        <SidebarMenu>
          {pins.map((name) => {
            const url = `/services/${name}`;
            const isActive = pathname === url;
            return (
              <SidebarMenuItem key={name}>
                <SidebarMenuButton asChild isActive={isActive} tooltip={name}>
                  <Link to={url}>
                    <Pin className="fill-current text-amber-500" />
                    <span>{name}</span>
                  </Link>
                </SidebarMenuButton>
                <SidebarMenuAction
                  showOnHover
                  aria-label={`Unpin ${name}`}
                  title="Unpin"
                  onClick={() => unpin(name)}
                >
                  <X />
                </SidebarMenuAction>
              </SidebarMenuItem>
            );
          })}
        </SidebarMenu>
      </nav>
    </SidebarGroup>
  );
}

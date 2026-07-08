import { useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";

import { AppSidebar } from "@/components/app-sidebar";
import { CommandMenu } from "@/components/command-menu";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";

export function Layout() {
  const { pathname } = useLocation();
  const [searchOpen, setSearchOpen] = useState(false);

  // ⌘K quick-jump search belongs on the services list (`/`). Pages render their
  // own header inline and start flush at the top — there's no shared top bar.
  const showSearch = pathname === "/";

  useEffect(() => {
    if (!showSearch) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setSearchOpen((prev) => !prev);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [showSearch]);

  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        <main className="flex flex-1 flex-col gap-4 p-4 md:rounded-t-xl">
          <Outlet />
        </main>
      </SidebarInset>
      {showSearch && (
        <CommandMenu open={searchOpen} onOpenChange={setSearchOpen} />
      )}
    </SidebarProvider>
  );
}

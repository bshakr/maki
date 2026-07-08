import { useNavigate } from "react-router-dom";

import { SERVICE_TABS, serviceTabPath, type ServiceTab } from "@/lib/service-tabs";
import { cn } from "@/lib/utils";

// URL-driven tab bar for the service detail page. Clicking a tab navigates to its route; the
// active tab is derived from the URL by the page and passed in. Optional `actions` render
// right-aligned on the same row (e.g. Refresh / Run task), sharing the bottom border.
export function ServiceTabs({
  name,
  active,
  actions,
}: {
  name: string;
  active: ServiceTab;
  actions?: React.ReactNode;
}) {
  const navigate = useNavigate();
  return (
    <div className="flex items-end justify-between gap-4 border-b">
      <nav role="tablist" aria-label="Service views" className="flex gap-1">
        {SERVICE_TABS.map((tab) => {
          const isActive = tab.key === active;
          return (
            <button
              key={tab.key}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => navigate(serviceTabPath(name, tab.key))}
              className={cn(
                "-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "border-foreground text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              {tab.label}
            </button>
          );
        })}
      </nav>
      {actions && <div className="flex items-center gap-2 pb-1.5">{actions}</div>}
    </div>
  );
}

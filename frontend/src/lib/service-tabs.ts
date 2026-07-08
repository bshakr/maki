// The service-detail tabs are URL-driven: the active tab is derived from the path segment after
// the service name, and clicking a tab navigates. Deploys is the default (bare service URL), and
// the deploy-detail deep link (/services/:name/deploys/:sha) also resolves to the Deploys tab.

export const SERVICE_TABS = [
  { key: "deploys", label: "Deploys" },
  { key: "tasks", label: "Tasks" },
  { key: "metrics", label: "Metrics" },
  { key: "env", label: "Env" },
] as const;

export type ServiceTab = (typeof SERVICE_TABS)[number]["key"];

const NON_DEFAULT: ReadonlySet<string> = new Set(["tasks", "metrics", "env"]);

/** Active tab for a `/services/:name[/...]` pathname. Anything that isn't tasks/metrics/env
 *  (bare service URL, or /deploys/:sha) is the default Deploys tab. */
export function deriveServiceTab(pathname: string): ServiceTab {
  const segment = pathname.split("/").filter(Boolean)[2]; // ["services", name, <segment?>]
  return segment && NON_DEFAULT.has(segment) ? (segment as ServiceTab) : "deploys";
}

/** URL for a service's tab. Deploys is the bare service URL; the rest append the tab key. */
export function serviceTabPath(name: string, tab: ServiceTab): string {
  const base = `/services/${encodeURIComponent(name)}`;
  return tab === "deploys" ? base : `${base}/${tab}`;
}

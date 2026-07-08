import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { App } from "./App";

beforeEach(() => {
  // App provides its own QueryClient; the pages fire real fetches on mount.
  // Resolve them so queries settle without unhandled rejections. The route
  // assertions below rely only on the synchronously-rendered loading shells.
  vi.spyOn(global, "fetch").mockResolvedValue({
    ok: true,
    json: async () => ({
      generated_at: "2026-05-31T09:00:00Z",
      services: [],
      items: [],
      service: "wfm-service",
      deployments: [],
    }),
  } as Response);
});

afterEach(() => vi.restoreAllMocks());

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

test("renders services page at root with sidebar nav", () => {
  renderAt("/");
  expect(screen.getByTestId("services-page")).toBeInTheDocument();
  // Scope link lookups to the sidebar nav: the breadcrumb also exposes a
  // "Services" element with role="link" on the root route.
  const nav = screen.getByRole("navigation", { name: /main/i });
  expect(within(nav).getByRole("link", { name: /services/i })).toBeInTheDocument();
  expect(within(nav).getByRole("link", { name: /activity/i })).toBeInTheDocument();
  expect(within(nav).getByRole("link", { name: /metrics/i })).toBeInTheDocument();
});

test("routes to activity and service detail", () => {
  renderAt("/activity");
  expect(screen.getByTestId("activity-page")).toBeInTheDocument();
  renderAt("/services/wfm-service");
  expect(screen.getByTestId("service-detail")).toBeInTheDocument();
});

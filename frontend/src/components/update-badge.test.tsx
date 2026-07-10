import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { UpdateBadge } from "@/components/update-badge";
import { SidebarProvider } from "@/components/ui/sidebar";

afterEach(() => vi.restoreAllMocks());

function mockVersion(body: unknown) {
  vi.spyOn(global, "fetch").mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => body,
  } as Response);
}

function renderBadge() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SidebarProvider>
        <UpdateBadge />
      </SidebarProvider>
    </QueryClientProvider>,
  );
}

test("shows the badge with a behind count when an update is available", async () => {
  mockVersion({
    current_sha: "aaa",
    upstream: "origin/main",
    behind_by: 4,
    update_available: true,
  });
  renderBadge();
  await waitFor(() =>
    expect(screen.getByText(/update available/i)).toBeInTheDocument(),
  );
  expect(screen.getByText(/4 commits behind/i)).toBeInTheDocument();
});

test("renders nothing when up to date", async () => {
  mockVersion({
    current_sha: "aaa",
    upstream: "origin/main",
    behind_by: null,
    update_available: false,
  });
  renderBadge();
  // Let the query settle, then assert the badge never appeared.
  await waitFor(() => expect(global.fetch).toHaveBeenCalled());
  expect(screen.queryByText(/update available/i)).not.toBeInTheDocument();
});

test("renders nothing while the check errors", async () => {
  vi.spyOn(global, "fetch").mockRejectedValue(new Error("network down"));
  renderBadge();
  await waitFor(() => expect(global.fetch).toHaveBeenCalled());
  expect(screen.queryByText(/update available/i)).not.toBeInTheDocument();
});

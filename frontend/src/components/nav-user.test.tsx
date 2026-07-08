import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, expect, test, vi } from "vitest";

import { NavUser } from "@/components/nav-user";
import { SidebarProvider } from "@/components/ui/sidebar";

afterEach(() => vi.restoreAllMocks());

function mockFetch(resp: Partial<Response> & { status: number; ok: boolean }) {
  vi.spyOn(global, "fetch").mockResolvedValue(resp as Response);
}

function renderNavUser(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SidebarProvider>{ui}</SidebarProvider>
    </QueryClientProvider>,
  );
}

test("shows the assumed identity name + account and derives initials", async () => {
  mockFetch({
    ok: true,
    status: 200,
    json: async () => ({
      account: "123456789012",
      arn: "arn:aws:sts::123456789012:assumed-role/AdminRole/bob.smith",
      user_id: "X",
      name: "bob.smith",
      region: "eu-west-1",
    }),
  });
  renderNavUser(<NavUser />);
  await waitFor(() =>
    expect(screen.getAllByText("bob.smith").length).toBeGreaterThan(0),
  );
  expect(screen.getAllByText(/account 123456789012/i).length).toBeGreaterThan(0);
  // "bob.smith" → "BS"
  expect(screen.getAllByText("BS").length).toBeGreaterThan(0);
});

test("degrades to a no-identity label when creds are unavailable", async () => {
  mockFetch({
    ok: false,
    status: 503,
    json: async () => ({ error: "aws_credentials_unavailable", detail: "x" }),
  });
  renderNavUser(<NavUser />);
  await waitFor(() =>
    expect(screen.getAllByText(/no aws identity/i).length).toBeGreaterThan(0),
  );
  expect(screen.queryByText(/bailey/i)).not.toBeInTheDocument();
});

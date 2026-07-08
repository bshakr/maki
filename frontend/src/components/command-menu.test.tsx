import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { renderWithProviders } from "@/test-utils";

import { CommandMenu } from "./command-menu";

afterEach(() => vi.restoreAllMocks());

const payload = {
  generated_at: "2026-05-29T09:00:00Z",
  services: [
    {
      name: "newsfeed",
      platform: "ecs",
      env: "production",
      git_sha: "abc123def456",
      image: "x/newsfeed:abc123def456",
      deployed_at: "2026-05-29T08:00:00Z",
      running_count: 2,
      desired_count: 2,
      status: "COMPLETED",
      commit_url: "https://github.com/acme/platform/commit/abc123def456",
    },
    {
      name: "inventory",
      platform: "amplify",
      env: "production",
      git_sha: "9f8e7d6c5b4",
      image: "x/inventory:9f8e7d6c5b4",
      deployed_at: "2026-05-29T08:57:00Z",
      running_count: 2,
      desired_count: 3,
      status: "IN_PROGRESS",
      commit_url: null,
    },
  ],
};

function mockFetch() {
  vi.spyOn(global, "fetch").mockResolvedValue({
    ok: true,
    json: async () => payload,
  } as Response);
}

function renderMenu(onOpenChange = vi.fn()) {
  return renderWithProviders(
    <CommandMenu open={true} onOpenChange={onOpenChange} />,
  );
}

test("lists services fetched when open", async () => {
  mockFetch();
  renderMenu();
  await waitFor(() =>
    expect(screen.getByText("newsfeed")).toBeInTheDocument(),
  );
  expect(screen.getByText("inventory")).toBeInTheDocument();
});

test("typing filters the service list", async () => {
  mockFetch();
  renderMenu();
  await waitFor(() =>
    expect(screen.getByText("newsfeed")).toBeInTheDocument(),
  );

  fireEvent.change(screen.getByPlaceholderText(/search services/i), {
    target: { value: "invent" },
  });

  await waitFor(() =>
    expect(screen.queryByText("newsfeed")).not.toBeInTheDocument(),
  );
  expect(screen.getByText("inventory")).toBeInTheDocument();
});

test("selecting a service closes the palette", async () => {
  const onOpenChange = vi.fn();
  mockFetch();
  renderMenu(onOpenChange);
  await waitFor(() =>
    expect(screen.getByText("inventory")).toBeInTheDocument(),
  );

  fireEvent.click(screen.getByText("inventory"));

  await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
});

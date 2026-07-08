import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { renderWithProviders } from "@/test-utils";

import { ServicesPage } from "./ServicesPage";

afterEach(() => vi.restoreAllMocks());

const services = [
  {
    name: "wfm-service",
    platform: "ecs",
    env: "production",
    git_sha: "a1b2c3d4e5",
    image: null,
    deployed_at: "2026-05-31T08:00:00Z",
    running_count: 2,
    desired_count: 2,
    pending_count: 0,
    status: "COMPLETED",
    commit_url: null,
    author: "bailey",
    author_avatar_url: null,
    message: "ship payroll engine",
    pr_url: null,
    committed_at: null,
  },
  {
    name: "inventory-service",
    platform: "ecs",
    env: "production",
    git_sha: "9f8e7d6c5b",
    image: null,
    deployed_at: "2026-05-31T08:30:00Z",
    running_count: 1,
    desired_count: 2,
    pending_count: 1,
    status: "IN_PROGRESS",
    commit_url: null,
    author: "bailey",
    author_avatar_url: null,
    message: "roll out inventory sync",
    pr_url: null,
    committed_at: null,
  },
  {
    name: "payments-service",
    platform: "ecs",
    env: "production",
    git_sha: "1122334455",
    image: null,
    deployed_at: "2026-05-31T07:00:00Z",
    running_count: 0,
    desired_count: 2,
    pending_count: 0,
    status: "FAILED",
    commit_url: null,
    author: "bailey",
    author_avatar_url: null,
    message: "bad rollout",
    pr_url: null,
    committed_at: null,
  },
];

const servicesPayload = { services, generated_at: "2026-05-31T09:00:00Z" };
const deployCountPayload = {
  count: 4,
  since: "2026-05-31T00:00:00Z",
  generated_at: "2026-05-31T09:00:00Z",
};

function mockFetchByUrl() {
  return vi.spyOn(global, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.includes("/api/activity/deploy-count")) {
      return { ok: true, json: async () => deployCountPayload } as Response;
    }
    return { ok: true, json: async () => servicesPayload } as Response;
  });
}

function renderPage() {
  mockFetchByUrl();
  return renderWithProviders(<ServicesPage />, { route: "/services" });
}

test("renders every fleet service", async () => {
  renderPage();
  await waitFor(() => expect(screen.getByText("wfm-service")).toBeInTheDocument());
  expect(screen.getByText("inventory-service")).toBeInTheDocument();
  expect(screen.getByText("payments-service")).toBeInTheDocument();
});

test("health rollup reflects one stable, one deploying, one degraded", async () => {
  renderPage();
  await waitFor(() =>
    expect(
      screen.getByRole("img", { name: "1 stable, 1 deploying, 1 degraded of 3 services" }),
    ).toBeInTheDocument(),
  );
});

test("deploys today renders the fleet-wide count from the activity feed", async () => {
  renderPage();
  await waitFor(() =>
    expect(screen.getByText("Deploys today").parentElement).toHaveTextContent("4"),
  );
});

test("filtering narrows the visible services to matches", async () => {
  renderPage();
  await waitFor(() => expect(screen.getByText("wfm-service")).toBeInTheDocument());

  fireEvent.change(screen.getByRole("textbox", { name: /filter services/i }), {
    target: { value: "wfm" },
  });

  await waitFor(() =>
    expect(screen.queryByText("inventory-service")).not.toBeInTheDocument(),
  );
  expect(screen.queryByText("payments-service")).not.toBeInTheDocument();
  expect(screen.getByText("wfm-service")).toBeInTheDocument();
});

test("a failed fetch renders the error state", async () => {
  vi.spyOn(global, "fetch").mockRejectedValue(new Error("network down"));
  renderWithProviders(<ServicesPage />, { route: "/services" });

  await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
  expect(screen.getByRole("alert")).toHaveTextContent("network down");
});

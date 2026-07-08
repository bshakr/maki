import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { renderWithProviders } from "@/test-utils";
import { fetchServiceEnv } from "@/api";

import { EnvTab } from "./env-tab";

vi.mock("@/api", () => ({ fetchServiceEnv: vi.fn() }));

const mockFetchServiceEnv = vi.mocked(fetchServiceEnv);

function makeResponse(overrides = {}) {
  return {
    service: "inventory",
    task_def: "inventory:42",
    containers: [
      {
        name: "app",
        environment: [
          { name: "LOG_LEVEL", value: "info" },
          { name: "REGION", value: "eu-west-1" },
        ],
        secrets: [
          {
            name: "DB_PASSWORD",
            value_from: "arn:aws:ssm:eu-west-1:123:parameter/db/pw",
          },
        ],
      },
    ],
    generated_at: "2026-05-31T10:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  mockFetchServiceEnv.mockReset();
});
afterEach(() => vi.restoreAllMocks());

test("env values are masked by default and revealed per-row", async () => {
  mockFetchServiceEnv.mockResolvedValue(makeResponse());
  renderWithProviders(<EnvTab service="inventory" />);

  await waitFor(() => expect(screen.getByText("LOG_LEVEL")).toBeInTheDocument());
  // Values are hidden by default (could be passwords) — masked, not the real value.
  expect(screen.queryByText("info")).not.toBeInTheDocument();
  expect(screen.getAllByText("••••••••").length).toBeGreaterThan(0);

  // Reveal the first value (LOG_LEVEL).
  fireEvent.click(screen.getAllByRole("button", { name: "Reveal value" })[0]);
  expect(screen.getByText("info")).toBeInTheDocument();
  // A copy-value control is present per row.
  expect(screen.getAllByRole("button", { name: "Copy value" }).length).toBe(2);
});

test("renders the secret ref (value_from) and never a secret value", async () => {
  mockFetchServiceEnv.mockResolvedValue(makeResponse());
  renderWithProviders(<EnvTab service="inventory" />);

  await waitFor(() =>
    expect(screen.getByText("DB_PASSWORD")).toBeInTheDocument(),
  );
  // The ref deep-links to the AWS SSM console (value resolved in AWS, never by maki).
  const link = screen.getByRole("link", {
    name: "arn:aws:ssm:eu-west-1:123:parameter/db/pw",
  });
  expect(link).toHaveAttribute(
    "href",
    expect.stringContaining("systems-manager/parameters"),
  );
  // There is no secret "value" anywhere in the schema or the DOM.
  expect(screen.queryByText("should-never-surface")).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Copy secret reference" }),
  ).toBeInTheDocument();
});

test("shows the task-def caption and a read-only affordance", async () => {
  mockFetchServiceEnv.mockResolvedValue(makeResponse());
  renderWithProviders(<EnvTab service="inventory" />);

  await waitFor(() => expect(screen.getByText("inventory:42")).toBeInTheDocument());
  expect(screen.getByText(/task def:/)).toBeInTheDocument();
  expect(screen.getByText("Read-only")).toBeInTheDocument();
});

test("groups by container and shows container names when there is more than one", async () => {
  mockFetchServiceEnv.mockResolvedValue(
    makeResponse({
      containers: [
        {
          name: "app",
          environment: [{ name: "A", value: "1" }],
          secrets: [],
        },
        {
          name: "sidecar",
          environment: [{ name: "B", value: "2" }],
          secrets: [],
        },
      ],
    }),
  );
  renderWithProviders(<EnvTab service="inventory" />);

  await waitFor(() => expect(screen.getByText("app")).toBeInTheDocument());
  expect(screen.getByText("sidecar")).toBeInTheDocument();
  expect(screen.getAllByTestId("env-container")).toHaveLength(2);
});

test("does not show a container heading for a single container", async () => {
  mockFetchServiceEnv.mockResolvedValue(makeResponse());
  renderWithProviders(<EnvTab service="inventory" />);

  await waitFor(() => expect(screen.getByText("LOG_LEVEL")).toBeInTheDocument());
  // Single container: the container name is not used as a subheading.
  expect(screen.queryByText("app")).not.toBeInTheDocument();
});

test("shows the empty state when no env and no secrets across all containers", async () => {
  mockFetchServiceEnv.mockResolvedValue(
    makeResponse({
      containers: [{ name: "app", environment: [], secrets: [] }],
    }),
  );
  renderWithProviders(<EnvTab service="inventory" />);

  await waitFor(() =>
    expect(screen.getByText("No environment configured.")).toBeInTheDocument(),
  );
});

test("shows an error state when the query fails", async () => {
  mockFetchServiceEnv.mockRejectedValue(new Error("Failed to load env: 500"));
  renderWithProviders(<EnvTab service="inventory" />);

  const alert = await waitFor(() => screen.getByRole("alert"));
  expect(within(alert).getByText("Failed to load env: 500")).toBeInTheDocument();
});

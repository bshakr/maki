import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { renderWithProviders } from "@/test-utils";
import { fetchMetrics, fetchTaskHistory } from "@/api";

import { MetricsTab } from "./metrics-tab";

vi.mock("@/api", () => ({ fetchMetrics: vi.fn(), fetchTaskHistory: vi.fn() }));

const mockFetchMetrics = vi.mocked(fetchMetrics);
const mockFetchTaskHistory = vi.mocked(fetchTaskHistory);

function makeTaskHistory(overrides = {}) {
  return {
    service: "wfm-service",
    range_days: 30,
    period_seconds: 3600,
    points: [
      { timestamp: "2026-05-30T10:00:00Z", running: 2, desired: 3 },
      { timestamp: "2026-05-30T11:00:00Z", running: 3, desired: 3 },
    ],
    generated_at: "2026-05-31T10:00:00Z",
    ...overrides,
  };
}

function makeResponse(overrides = {}) {
  return {
    range_days: 30,
    service: "wfm-service",
    deploy_count: 12,
    deploys_per_day: 0.4,
    lead_time_median_seconds: 11520, // 3h 12m
    lead_time_p90_seconds: 21600, // 6h 0m
    ci_median_seconds: 3600, // 1h
    rollout_median_seconds: 7200, // 2h
    last_deployed_at: "2026-05-31T09:00:00Z",
    trend: [
      { date: "2026-05-30", count: 7 },
      { date: "2026-05-31", count: 5 },
    ],
    lead_time_trend: [
      { date: "2026-05-30", median_seconds: 10800 },
      { date: "2026-05-31", median_seconds: null },
    ],
    services: ["wfm-service"],
    generated_at: "2026-05-31T10:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  mockFetchMetrics.mockReset();
  mockFetchTaskHistory.mockReset();
  mockFetchTaskHistory.mockResolvedValue(makeTaskHistory());
});
afterEach(() => vi.restoreAllMocks());

test("the time-to-deploy tile shows the median and p90", async () => {
  mockFetchMetrics.mockResolvedValue(makeResponse());
  renderWithProviders(<MetricsTab service="wfm-service" />);

  const tile = (await waitFor(() =>
    screen.getByText("Time to deploy").closest("[data-slot=card]"),
  )) as HTMLElement;
  expect(within(tile).getByText("3h 12m")).toBeInTheDocument();
  expect(within(tile).getByText(/p90 6h 0m · merged → live/)).toBeInTheDocument();
});

test("renders the frequency, rollout, and last-deploy tiles", async () => {
  mockFetchMetrics.mockResolvedValue(makeResponse());
  renderWithProviders(<MetricsTab service="wfm-service" />);

  await waitFor(() =>
    expect(screen.getByText("Deploy frequency")).toBeInTheDocument(),
  );
  expect(screen.getByText("0.4")).toBeInTheDocument();
  expect(screen.getByText("/day")).toBeInTheDocument();
  expect(screen.getByText("12 in last 30d")).toBeInTheDocument();

  // Rollout median tile.
  const rolloutTile = screen
    .getByText("Rollout (median)")
    .closest("[data-slot=card]") as HTMLElement;
  expect(within(rolloutTile).getByText("2h 0m")).toBeInTheDocument();

  expect(screen.getByText("Last deploy")).toBeInTheDocument();
});

test("CI vs rollout breakdown shows both labelled medians", async () => {
  mockFetchMetrics.mockResolvedValue(makeResponse());
  renderWithProviders(<MetricsTab service="wfm-service" />);

  const breakdown = await waitFor(() =>
    screen.getByTestId("ci-rollout-breakdown"),
  );
  expect(within(breakdown).getByText("CI/build")).toBeInTheDocument();
  expect(within(breakdown).getByText("1h 0m")).toBeInTheDocument();
  expect(within(breakdown).getByText("Rollout")).toBeInTheDocument();
  expect(within(breakdown).getByText("2h 0m")).toBeInTheDocument();
});

test("the time-to-deploy tile renders — when the median is null", async () => {
  mockFetchMetrics.mockResolvedValue(
    makeResponse({ lead_time_median_seconds: null, lead_time_p90_seconds: null }),
  );
  renderWithProviders(<MetricsTab service="wfm-service" />);

  const tile = (await waitFor(() =>
    screen.getByText("Time to deploy").closest("[data-slot=card]"),
  )) as HTMLElement;
  expect(within(tile).getByText("—")).toBeInTheDocument();
});

test("shows the empty state when there are no deploys in range", async () => {
  mockFetchMetrics.mockResolvedValue(
    makeResponse({ deploy_count: 0, deploys_per_day: 0, trend: [], lead_time_trend: [] }),
  );
  renderWithProviders(<MetricsTab service="wfm-service" />);

  await waitFor(() =>
    expect(screen.getByText("No deploys in this range.")).toBeInTheDocument(),
  );
});

test("changing the range refetches with the new rangeDays", async () => {
  mockFetchMetrics.mockResolvedValue(makeResponse());
  renderWithProviders(<MetricsTab service="wfm-service" />);

  // Wait for the loaded UI before interacting with the range control.
  await waitFor(() =>
    expect(screen.getByText("Time to deploy")).toBeInTheDocument(),
  );
  expect(mockFetchMetrics).toHaveBeenCalledWith({
    service: "wfm-service",
    rangeDays: 30,
  });

  fireEvent.click(screen.getByRole("button", { name: "7d" }));

  await waitFor(() =>
    expect(mockFetchMetrics).toHaveBeenCalledWith({
      service: "wfm-service",
      rangeDays: 7,
    }),
  );
});

test("renders the Tasks over time card and fetches task history for the range", async () => {
  mockFetchMetrics.mockResolvedValue(makeResponse());
  renderWithProviders(<MetricsTab service="wfm-service" />);

  const card = await waitFor(() => screen.getByTestId("tasks-over-time"));
  expect(within(card).getByText("Tasks over time")).toBeInTheDocument();
  // With data, the chart (not the empty state) is rendered.
  expect(
    within(card).queryByText("No task data in this range."),
  ).not.toBeInTheDocument();
  await waitFor(() =>
    expect(mockFetchTaskHistory).toHaveBeenCalledWith("wfm-service", {
      rangeDays: 30,
    }),
  );
});

test("Tasks over time shows the empty state when there are no points", async () => {
  mockFetchMetrics.mockResolvedValue(makeResponse());
  mockFetchTaskHistory.mockResolvedValue(makeTaskHistory({ points: [] }));
  renderWithProviders(<MetricsTab service="wfm-service" />);

  const card = await waitFor(() => screen.getByTestId("tasks-over-time"));
  expect(
    within(card).getByText("No task data in this range."),
  ).toBeInTheDocument();
});

import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { renderWithProviders } from "@/test-utils";
import { fetchMetrics } from "@/api";

import { MetricsPage } from "./MetricsPage";

vi.mock("@/api", () => ({ fetchMetrics: vi.fn() }));

const mockFetchMetrics = vi.mocked(fetchMetrics);

function makeResponse(overrides = {}) {
  return {
    range_days: 30,
    service: "all",
    deploy_count: 12,
    deploys_per_day: 0.4,
    lead_time_median_seconds: 11520, // 3h 12m
    lead_time_p90_seconds: 21600, // 6h
    ci_median_seconds: 600,
    rollout_median_seconds: 300,
    last_deployed_at: "2026-05-31T09:00:00Z",
    failed_count: 1,
    rollback_count: 1,
    change_fail_rate: 2 / 12,
    fail_trend: [
      { date: "2026-05-30", count: 1 },
      { date: "2026-05-31", count: 1 },
    ],
    mttr_median_seconds: 5400, // 1h 30m
    previous: {
      deploys_per_day: 0.2,
      lead_time_median_seconds: 14400, // 4h (current is faster → good)
      change_fail_rate: 0.1,
      mttr_median_seconds: 7200,
    },
    slowest_deploys: [
      {
        service: "inventory",
        sha: "aaaaaaa111",
        author: "bailey",
        lead_seconds: 21600,
        deployed_at: "2026-05-30T10:00:00Z",
      },
      {
        service: "workforce",
        sha: "bbbbbbb222",
        author: "priya",
        lead_seconds: 18000,
        deployed_at: "2026-05-29T10:00:00Z",
      },
    ],
    fastest_deploys: [
      {
        service: "forecasting",
        sha: "ccccccc333",
        author: "diego",
        lead_seconds: 300,
        deployed_at: "2026-05-31T08:00:00Z",
      },
    ],
    trend: [
      { date: "2026-05-30", count: 7 },
      { date: "2026-05-31", count: 5 },
    ],
    lead_time_trend: [
      { date: "2026-05-30", median_seconds: 10000, ci_median_seconds: null, rollout_median_seconds: null },
      { date: "2026-05-31", median_seconds: 12000, ci_median_seconds: null, rollout_median_seconds: null },
    ],
    services: ["forecasting", "inventory"],
    generated_at: "2026-05-31T10:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  mockFetchMetrics.mockReset();
});

afterEach(() => vi.restoreAllMocks());

test("renders the four DORA KPI cards with formatted values", async () => {
  mockFetchMetrics.mockResolvedValue(makeResponse());
  renderWithProviders(<MetricsPage />);

  await waitFor(() =>
    expect(screen.getByText("Deploy frequency")).toBeInTheDocument(),
  );

  expect(screen.getByText("Lead time (median)")).toBeInTheDocument();
  expect(screen.getByText("Change-fail rate")).toBeInTheDocument();
  expect(screen.getByText("MTTR")).toBeInTheDocument();

  expect(screen.getByText("0.40")).toBeInTheDocument();
  expect(screen.getByText("/day")).toBeInTheDocument();
  expect(screen.getByText("3h 12m")).toBeInTheDocument(); // lead median
  expect(screen.getByText("16.7%")).toBeInTheDocument(); // change-fail rate
  expect(screen.getByText("1h 30m")).toBeInTheDocument(); // MTTR
});

test("renders DORA band badges on KPI cards", async () => {
  mockFetchMetrics.mockResolvedValue(makeResponse());
  renderWithProviders(<MetricsPage />);

  await waitFor(() =>
    expect(screen.getByText("Deploy frequency")).toBeInTheDocument(),
  );

  // 0.4/day → High; lead 3h12m → Elite; cfr 16.7% → Low; mttr 1h30m → High.
  expect(screen.getAllByText("Elite").length).toBeGreaterThanOrEqual(1);
  expect(screen.getAllByText("High").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText("Low")).toBeInTheDocument();
});

test("shows — for lead time and MTTR when null", async () => {
  mockFetchMetrics.mockResolvedValue(
    makeResponse({ lead_time_median_seconds: null, mttr_median_seconds: null }),
  );
  renderWithProviders(<MetricsPage />);

  await waitFor(() =>
    expect(screen.getByText("Lead time (median)")).toBeInTheDocument(),
  );

  const leadCard = screen
    .getByText("Lead time (median)")
    .closest("[data-slot=card]");
  // The big value renders "—"; the delta also renders "—" when previous is set but the
  // current value is null, so assert the value span specifically.
  const leadValue = leadCard?.querySelector(".text-3xl");
  expect(leadValue?.textContent).toBe("—");

  const mttrCard = screen.getByText("MTTR").closest("[data-slot=card]");
  expect(mttrCard?.querySelector(".text-3xl")?.textContent).toBe("—");
});

test("renders slowest and fastest leaderboards", async () => {
  mockFetchMetrics.mockResolvedValue(makeResponse());
  renderWithProviders(<MetricsPage />);

  await waitFor(() =>
    expect(screen.getByText("Slowest deploys")).toBeInTheDocument(),
  );
  expect(screen.getByText("Fastest deploys")).toBeInTheDocument();

  const slowCard = screen.getByText("Slowest deploys").closest("[data-slot=card]");
  // Slowest first row: inventory · aaaaaaa (short sha) · bailey · 6h.
  expect(within(slowCard as HTMLElement).getByText("inventory")).toBeInTheDocument();
  expect(within(slowCard as HTMLElement).getByText("aaaaaaa")).toBeInTheDocument();
  expect(within(slowCard as HTMLElement).getByText("6h 0m")).toBeInTheDocument();

  const fastCard = screen.getByText("Fastest deploys").closest("[data-slot=card]");
  expect(within(fastCard as HTMLElement).getByText("forecasting")).toBeInTheDocument();
  expect(within(fastCard as HTMLElement).getByText("5m")).toBeInTheDocument();
});

test("rows link to the deploy sheet (whole row, short sha in the URL)", async () => {
  mockFetchMetrics.mockResolvedValue(makeResponse());
  renderWithProviders(<MetricsPage />);

  await waitFor(() =>
    expect(screen.getByText("Slowest deploys")).toBeInTheDocument(),
  );
  // The whole leaderboard row is the link; the URL carries the short sha.
  const link = screen
    .getAllByRole("link")
    .find(
      (l) =>
        l.getAttribute("href") === "/services/inventory/deploys/aaaaaaa",
    );
  expect(link).toBeTruthy();
});

test("shows delta direction vs previous period", async () => {
  mockFetchMetrics.mockResolvedValue(makeResponse());
  renderWithProviders(<MetricsPage />);

  await waitFor(() =>
    expect(screen.getByText("Deploy frequency")).toBeInTheDocument(),
  );

  const freqCard = screen
    .getByText("Deploy frequency")
    .closest("[data-slot=card]");
  // 0.4 vs 0.2 → up.
  expect(
    within(freqCard as HTMLElement).getByTestId("delta"),
  ).toHaveAttribute("data-direction", "up");

  const leadCard = screen
    .getByText("Lead time (median)")
    .closest("[data-slot=card]");
  // 11520 vs 14400 → down (and good, since lower lead time is better).
  expect(
    within(leadCard as HTMLElement).getByTestId("delta"),
  ).toHaveAttribute("data-direction", "down");
});

test("shows empty state when deploy_count is 0", async () => {
  mockFetchMetrics.mockResolvedValue(
    makeResponse({
      deploy_count: 0,
      deploys_per_day: 0,
      trend: [],
      fail_trend: [],
      slowest_deploys: [],
      fastest_deploys: [],
    }),
  );
  renderWithProviders(<MetricsPage />);

  await waitFor(() =>
    expect(screen.getByText("No deploys in the last 30d")).toBeInTheDocument(),
  );
});

test("changing the range select refetches with new rangeDays", async () => {
  mockFetchMetrics.mockResolvedValue(makeResponse());
  renderWithProviders(<MetricsPage />);

  await waitFor(() => expect(screen.getByText("30d")).toBeInTheDocument());
  expect(mockFetchMetrics).toHaveBeenCalledWith({
    rangeDays: 30,
    service: "all",
    refresh: false,
  });

  fireEvent.click(screen.getByText("30d"));
  fireEvent.click(await screen.findByRole("option", { name: "7d" }));

  await waitFor(() =>
    expect(mockFetchMetrics).toHaveBeenCalledWith({
      rangeDays: 7,
      service: "all",
      refresh: false,
    }),
  );
});

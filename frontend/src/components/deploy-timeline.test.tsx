import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { renderWithProviders } from "@/test-utils";
import { fetchDeployTimeline, type DeployTimeline as Timeline } from "@/api";

import { DeployTimeline } from "./deploy-timeline";

vi.mock("@/api", () => ({ fetchDeployTimeline: vi.fn() }));

const mockFetch = vi.mocked(fetchDeployTimeline);

function makeTimeline(overrides: Partial<Timeline> = {}): Timeline {
  return {
    service: "wfm-service",
    sha: "a1b2c3d",
    merged_at: "2026-05-29T04:00:00Z",
    live_at: "2026-05-29T04:05:16Z",
    total_seconds: 316,
    segments: [
      // A tiny phase (9s) — its label must remain readable in the left column.
      {
        key: "ci:lint",
        label: "Lint",
        source: "github_actions",
        start: "2026-05-29T04:00:05Z",
        end: "2026-05-29T04:00:14Z",
        seconds: 9,
        status: "success",
        count: 1,
      },
      // A zero-duration phase — present for honesty but visually quiet (no bar).
      {
        key: "ci:test-results",
        label: "Test Results",
        source: "github_actions",
        start: "2026-05-29T04:00:20Z",
        end: "2026-05-29T04:00:20Z",
        seconds: 0,
        status: "success",
        count: 1,
      },
      // Two CI phases that overlap in wall-clock time.
      {
        key: "ci:test",
        label: "Test",
        source: "github_actions",
        start: "2026-05-29T04:00:30Z",
        end: "2026-05-29T04:02:00Z",
        seconds: 90,
        status: "success",
        count: 4,
      },
      {
        key: "ci:publish-images",
        label: "publish-images",
        source: "github_actions",
        start: "2026-05-29T04:01:00Z",
        end: "2026-05-29T04:02:10Z",
        seconds: 70,
        status: "success",
        count: 10,
      },
      {
        key: "ecs:queued",
        label: "Queued",
        source: "ecs",
        start: "2026-05-29T04:02:00Z",
        end: "2026-05-29T04:02:12Z",
        seconds: 12,
        status: "success",
        count: 1,
      },
      {
        key: "ecs:rollout",
        label: "Rollout",
        source: "ecs",
        start: "2026-05-29T04:02:12Z",
        end: "2026-05-29T04:05:16Z",
        seconds: 184,
        status: "in_progress",
        count: 1,
      },
    ],
    generated_at: "2026-05-29T09:00:00Z",
    ...overrides,
  };
}

// CI-only timeline: no ECS segments, axis end (live_at) well after the last CI
// phase ends — exercises the "rollout · no data" tail.
function makeCiOnlyTimeline(): Timeline {
  return makeTimeline({
    segments: [
      {
        key: "ci:test",
        label: "Test",
        source: "github_actions",
        start: "2026-05-29T04:00:30Z",
        end: "2026-05-29T04:02:00Z",
        seconds: 90,
        status: "success",
        count: 4,
      },
    ],
  });
}

beforeEach(() => {
  mockFetch.mockReset();
});

afterEach(() => vi.restoreAllMocks());

test("renders one labeled row per phase with label + duration in the left column", async () => {
  mockFetch.mockResolvedValue(makeTimeline());
  renderWithProviders(<DeployTimeline service="wfm-service" />);

  await waitFor(() =>
    expect(screen.getByTestId("timeline-gantt")).toBeInTheDocument(),
  );

  expect(screen.getByText("Time to prod ·")).toBeInTheDocument();

  // One row per segment.
  expect(screen.getAllByTestId("timeline-row")).toHaveLength(6);

  // Every phase label is present in its row.
  expect(screen.getByText("Lint")).toBeInTheDocument();
  expect(screen.getByText("Test")).toBeInTheDocument();
  expect(screen.getByText("publish-images")).toBeInTheDocument();
  expect(screen.getByText("Queued")).toBeInTheDocument();
  expect(screen.getByText("Rollout")).toBeInTheDocument();
});

test("groups rows under CI (GitHub Actions) and Rollout (ECS) subheads", async () => {
  mockFetch.mockResolvedValue(makeTimeline());
  renderWithProviders(<DeployTimeline service="wfm-service" />);

  await waitFor(() =>
    expect(screen.getByTestId("timeline-gantt")).toBeInTheDocument(),
  );

  // Both subheads render.
  expect(screen.getByText("CI (GitHub Actions)")).toBeInTheDocument();
  expect(screen.getByText("Rollout (ECS)")).toBeInTheDocument();

  // CI section holds the github_actions phases (and not the ECS ones).
  const ci = screen.getByTestId("timeline-section-ci");
  expect(within(ci).getByText("Lint")).toBeInTheDocument();
  expect(within(ci).getByText("Test")).toBeInTheDocument();
  expect(within(ci).getByText("publish-images")).toBeInTheDocument();
  expect(within(ci).queryByText("Rollout")).not.toBeInTheDocument();

  // Rollout section holds the ECS phases.
  const rollout = screen.getByTestId("timeline-section-rollout");
  expect(within(rollout).getByText("Queued")).toBeInTheDocument();
  expect(within(rollout).getByText("Rollout")).toBeInTheDocument();
  expect(within(rollout).queryByText("Lint")).not.toBeInTheDocument();
});

test("a 0s phase renders muted with a tick (no colored bar)", async () => {
  mockFetch.mockResolvedValue(makeTimeline());
  renderWithProviders(<DeployTimeline service="wfm-service" />);

  await waitFor(() =>
    expect(screen.getByTestId("timeline-gantt")).toBeInTheDocument(),
  );

  const row = screen
    .getByText("Test Results")
    .closest("[data-testid='timeline-row']") as HTMLElement;
  // Quiet styling on the label column.
  expect(row.querySelector(".text-muted-foreground")).not.toBeNull();
  // No colored bar — just a faint tick.
  expect(within(row).queryByTestId("timeline-bar")).not.toBeInTheDocument();
  expect(within(row).getByTestId("timeline-tick")).toBeInTheDocument();
});

test("the no-data band lives under the Rollout (ECS) subhead", async () => {
  mockFetch.mockResolvedValue(makeCiOnlyTimeline());
  renderWithProviders(<DeployTimeline service="wfm-service" />);

  await waitFor(() =>
    expect(screen.getByTestId("timeline-gantt")).toBeInTheDocument(),
  );

  const rollout = screen.getByTestId("timeline-section-rollout");
  expect(within(rollout).getByText("Rollout (ECS)")).toBeInTheDocument();
  expect(within(rollout).getByTestId("timeline-nodata")).toBeInTheDocument();
});

test("a tiny (9s) phase still shows its label and a positioned colored bar", async () => {
  mockFetch.mockResolvedValue(makeTimeline());
  renderWithProviders(<DeployTimeline service="wfm-service" />);

  await waitFor(() =>
    expect(screen.getByTestId("timeline-gantt")).toBeInTheDocument(),
  );

  const lint = screen.getByText("Lint").closest("[data-testid='timeline-row']");
  expect(lint).not.toBeNull();
  // Label readable in the left column; duration shown.
  expect(within(lint as HTMLElement).getByText("9s")).toBeInTheDocument();
  // The bar carries a positioned left + width and a background color.
  const bar = within(lint as HTMLElement).getByTestId("timeline-bar");
  expect(bar.style.left).toBeTruthy();
  expect(bar.style.width).toBeTruthy();
  expect(bar.style.backgroundColor).toBeTruthy();
});

test("bars are positioned with non-zero offsets (wall-clock, not stacked from 0)", async () => {
  mockFetch.mockResolvedValue(makeTimeline());
  renderWithProviders(<DeployTimeline service="wfm-service" />);

  await waitFor(() =>
    expect(screen.getByTestId("timeline-gantt")).toBeInTheDocument(),
  );

  const bars = screen.getAllByTestId("timeline-bar");
  const hasOffset = bars.some((b) => {
    const left = b.style.left;
    return left && left !== "0%" && parseFloat(left) > 0;
  });
  expect(hasOffset).toBe(true);
});

test("×count is shown for collapsed phases with count > 1", async () => {
  mockFetch.mockResolvedValue(makeTimeline());
  renderWithProviders(<DeployTimeline service="wfm-service" />);

  await waitFor(() =>
    expect(screen.getByTestId("timeline-gantt")).toBeInTheDocument(),
  );
  expect(screen.getByText("×4")).toBeInTheDocument();
  expect(screen.getByText("×10")).toBeInTheDocument();
});

test("a failed phase is red and an in_progress phase pulses", async () => {
  mockFetch.mockResolvedValue(
    makeTimeline({
      segments: [
        {
          key: "ci:test",
          label: "Test",
          source: "github_actions",
          start: "2026-05-29T04:00:30Z",
          end: "2026-05-29T04:02:00Z",
          seconds: 90,
          status: "failed",
          count: 1,
        },
        {
          key: "ecs:rollout",
          label: "Rollout",
          source: "ecs",
          start: "2026-05-29T04:02:12Z",
          end: "2026-05-29T04:05:16Z",
          seconds: 184,
          status: "in_progress",
          count: 1,
        },
      ],
    }),
  );
  renderWithProviders(<DeployTimeline service="wfm-service" />);

  await waitFor(() =>
    expect(screen.getByTestId("timeline-gantt")).toBeInTheDocument(),
  );

  const failedRow = screen
    .getByText("Test")
    .closest("[data-testid='timeline-row']") as HTMLElement;
  const failedBar = within(failedRow).getByTestId("timeline-bar");
  // #dc2626 → rgb(220, 38, 38)
  expect(failedBar.style.backgroundColor).toBe("rgb(220, 38, 38)");

  const progressRow = screen
    .getByText("Rollout")
    .closest("[data-testid='timeline-row']") as HTMLElement;
  const progressBar = within(progressRow).getByTestId("timeline-bar");
  expect(progressBar.className).toContain("animate-pulse");
  // #d97706 → rgb(217, 119, 6)
  expect(progressBar.style.backgroundColor).toBe("rgb(217, 119, 6)");
});

test("renders 'rollout · no data' tail when only CI segments exist", async () => {
  mockFetch.mockResolvedValue(makeCiOnlyTimeline());
  renderWithProviders(<DeployTimeline service="wfm-service" />);

  await waitFor(() =>
    expect(screen.getByTestId("timeline-gantt")).toBeInTheDocument(),
  );

  expect(screen.getByTestId("timeline-nodata")).toBeInTheDocument();
  expect(screen.getByText("no data")).toBeInTheDocument();
});

test("does NOT render the no-data tail when ECS segments are present", async () => {
  mockFetch.mockResolvedValue(makeTimeline());
  renderWithProviders(<DeployTimeline service="wfm-service" />);

  await waitFor(() =>
    expect(screen.getByTestId("timeline-gantt")).toBeInTheDocument(),
  );

  expect(screen.queryByTestId("timeline-nodata")).not.toBeInTheDocument();
});

test("empty segments shows the no-timeline message", async () => {
  mockFetch.mockResolvedValue(
    makeTimeline({ segments: [], total_seconds: null }),
  );
  renderWithProviders(<DeployTimeline service="wfm-service" />);

  await waitFor(() =>
    expect(screen.getByText("No timeline available")).toBeInTheDocument(),
  );
});

test("renders a 'View CI run' link pointing at the first run URL", async () => {
  mockFetch.mockResolvedValue(
    makeTimeline({
      run_urls: ["https://github.com/acme/platform/actions/runs/101"],
    }),
  );
  renderWithProviders(<DeployTimeline service="wfm-service" />);

  await waitFor(() =>
    expect(screen.getByTestId("timeline-gantt")).toBeInTheDocument(),
  );

  const link = screen.getByText("View CI run").closest("a");
  expect(link).toHaveAttribute(
    "href",
    "https://github.com/acme/platform/actions/runs/101",
  );
  expect(link).toHaveAttribute("target", "_blank");
});

test("renders an extra small link per additional run beyond the first", async () => {
  mockFetch.mockResolvedValue(
    makeTimeline({
      run_urls: [
        "https://github.com/acme/platform/actions/runs/101",
        "https://github.com/acme/platform/actions/runs/102",
      ],
    }),
  );
  renderWithProviders(<DeployTimeline service="wfm-service" />);

  await waitFor(() =>
    expect(screen.getByTestId("timeline-gantt")).toBeInTheDocument(),
  );

  const extra = screen.getByText("+1 more").closest("a");
  expect(extra).toHaveAttribute(
    "href",
    "https://github.com/acme/platform/actions/runs/102",
  );
});

test("no CI run link when run_urls is empty or absent", async () => {
  mockFetch.mockResolvedValue(makeTimeline({ run_urls: [] }));
  renderWithProviders(<DeployTimeline service="wfm-service" />);

  await waitFor(() =>
    expect(screen.getByTestId("timeline-gantt")).toBeInTheDocument(),
  );

  expect(screen.queryByTestId("timeline-run-links")).not.toBeInTheDocument();
});

test("error state shows the unavailable message", async () => {
  mockFetch.mockRejectedValue(new Error("boom"));
  renderWithProviders(<DeployTimeline service="wfm-service" />);

  await waitFor(() =>
    expect(screen.getByText("Timeline unavailable")).toBeInTheDocument(),
  );
});

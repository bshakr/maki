import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { renderWithProviders } from "@/test-utils";
import { fetchDeployTimeline, fetchRollout, type DeployedService } from "@/api";

import { CurrentDeploySection } from "./current-deploy-section";

vi.mock("@/api", () => ({ fetchDeployTimeline: vi.fn(), fetchRollout: vi.fn() }));

const mockTimeline = vi.mocked(fetchDeployTimeline);
const mockRollout = vi.mocked(fetchRollout);

const svc: DeployedService = {
  name: "wfm-service",
  platform: "ecs",
  env: "production",
  git_sha: "a1b2c3d4e5f6",
  image: "123456789012.dkr.ecr.eu-west-1.amazonaws.com/wfm-service:a1b2c3d",
  deployed_at: "2026-05-29T07:00:00Z",
  running_count: 4,
  desired_count: 4,
  pending_count: 0,
  status: "COMPLETED",
  commit_url: "https://github.com/acme/platform/commit/a1b2c3d4e5f6",
  author: "bailey",
  author_avatar_url: null,
  message: "ship payroll engine",
  pr_url: "https://github.com/acme/platform/pull/4242",
  committed_at: "2026-05-29T04:00:00Z",
};

beforeEach(() => {
  mockTimeline.mockReset();
  mockTimeline.mockResolvedValue({
    service: "wfm-service",
    sha: "a1b2c3d",
    merged_at: "2026-05-29T04:00:00Z",
    live_at: "2026-05-29T04:05:16Z",
    total_seconds: 316,
    segments: [
      {
        key: "ci:test",
        label: "Test",
        source: "github_actions",
        start: "2026-05-29T04:00:30Z",
        end: "2026-05-29T04:02:00Z",
        seconds: 90,
        status: "success",
        count: 1,
      },
    ],
    generated_at: "2026-05-29T09:00:00Z",
  });
  mockRollout.mockReset();
  mockRollout.mockResolvedValue({
    service: "wfm-service",
    deployments: [
      {
        status: "PRIMARY",
        rollout_state: "COMPLETED",
        rollout_reason: "ECS deployment ecs-svc/1 completed.",
        desired_count: 4,
        running_count: 4,
        pending_count: 0,
        failed_tasks: 0,
        task_definition: "arn:td:wfm-service:6",
        created_at: "2026-05-29T06:55:00Z",
        updated_at: "2026-05-29T07:00:00Z",
      },
    ],
    in_progress: false,
    generated_at: "2026-05-29T09:00:00Z",
  });
});

afterEach(() => vi.restoreAllMocks());

test("the timeline is hidden by default behind a 'View timeline' trigger", () => {
  renderWithProviders(<CurrentDeploySection svc={svc} />);

  expect(screen.getByText("View timeline")).toBeInTheDocument();
  // Collapsed: the timeline content is not rendered yet.
  expect(screen.queryByTestId("deploy-timeline")).not.toBeInTheDocument();
});

test("time-to-prod uses the timeline's rollout total, not the drifting deployed_at", async () => {
  // svc.committed_at→deployed_at would be 3h; the ECS rollout total is 316s (5m).
  // The tile must trust the rollout total so post-deploy task churn doesn't inflate it.
  renderWithProviders(<CurrentDeploySection svc={svc} />);
  await waitFor(() => expect(screen.getByText("5m")).toBeInTheDocument());
  expect(screen.queryByText("3h 0m")).not.toBeInTheDocument();
});

test("clicking 'View timeline' reveals the embedded deploy timeline", async () => {
  renderWithProviders(<CurrentDeploySection svc={svc} />);

  fireEvent.click(screen.getByText("View timeline"));

  await waitFor(() =>
    expect(screen.getByTestId("deploy-timeline")).toBeInTheDocument(),
  );
  // The embedded timeline fetches + renders its grouped content.
  await waitFor(() =>
    expect(screen.getByTestId("timeline-gantt")).toBeInTheDocument(),
  );
});

test("an in-progress rollout shows the PRIMARY state and a draining ACTIVE line", async () => {
  mockRollout.mockResolvedValue({
    service: "wfm-service",
    deployments: [
      {
        status: "PRIMARY",
        rollout_state: "IN_PROGRESS",
        rollout_reason: "ECS deployment ecs-svc/2 in progress.",
        desired_count: 3,
        running_count: 1,
        pending_count: 2,
        failed_tasks: 0,
        task_definition: "arn:td:wfm-service:7",
        created_at: "2026-05-29T08:55:00Z",
        updated_at: "2026-05-29T08:55:00Z",
      },
      {
        status: "ACTIVE",
        rollout_state: null,
        rollout_reason: null,
        desired_count: 3,
        running_count: 2,
        pending_count: 0,
        failed_tasks: 0,
        task_definition: "arn:td:wfm-service:6",
        created_at: "2026-05-29T06:55:00Z",
        updated_at: "2026-05-29T06:55:00Z",
      },
    ],
    in_progress: true,
    generated_at: "2026-05-29T09:00:00Z",
  });

  renderWithProviders(<CurrentDeploySection svc={svc} />);

  expect(await screen.findByText("IN_PROGRESS")).toBeInTheDocument();
  expect(
    screen.getByText("1 running · 2 pending · of 3 desired"),
  ).toBeInTheDocument();
  expect(screen.getByText("2 still running")).toBeInTheDocument();
});

test("a completed rollout with a single deployment hides the rollout block", async () => {
  renderWithProviders(<CurrentDeploySection svc={svc} />);

  await waitFor(() => expect(mockRollout).toHaveBeenCalled());
  expect(screen.queryByText("Rollout")).not.toBeInTheDocument();
  expect(screen.queryByText("IN_PROGRESS")).not.toBeInTheDocument();
});

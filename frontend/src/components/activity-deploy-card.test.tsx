import { screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { renderWithProviders } from "@/test-utils";
import type { ActivityItem } from "@/api";

import { ActivityDeployCard } from "./activity-deploy-card";

function item(overrides: Partial<ActivityItem>): ActivityItem {
  return {
    id: 1,
    service: "wfm-service",
    platform: "ecs",
    sha: "abc1234def",
    deployed_at: "2026-06-05T10:00:00Z",
    status: "success",
    is_rollback: false,
    author: "bailey",
    author_avatar_url: null,
    message: "ship it",
    commit_url: null,
    pr_url: null,
    committed_at: null,
    ...overrides,
  };
}

test("rollback wins over status and shows the rollback badge", () => {
  renderWithProviders(
    <ActivityDeployCard item={item({ is_rollback: true, status: "success" })} />,
  );
  expect(screen.getByText("rollback")).toBeTruthy();
  expect(screen.getByTestId("activity-card").getAttribute("data-state")).toBe(
    "rollback",
  );
});

test("failed rollout shows the failed badge", () => {
  renderWithProviders(<ActivityDeployCard item={item({ status: "failed" })} />);
  expect(screen.getByText("failed")).toBeTruthy();
});

test("in-progress rollout shows a live 'deploying' marker", () => {
  renderWithProviders(
    <ActivityDeployCard item={item({ status: "in_progress" })} />,
  );
  expect(screen.getByText("deploying")).toBeTruthy();
});

test("plain success is marked but quiet (no badge)", () => {
  renderWithProviders(<ActivityDeployCard item={item({ status: "success" })} />);
  expect(screen.getByLabelText("succeeded")).toBeTruthy();
  expect(screen.queryByText("rollback")).toBeNull();
  expect(screen.queryByText("failed")).toBeNull();
});

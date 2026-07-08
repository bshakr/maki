import { expect, test } from "vitest";

import type { DeployedService } from "@/api";
import { healthOf } from "@/lib/health";

function svc(over: Partial<DeployedService>): DeployedService {
  return {
    name: "s",
    platform: "ecs",
    env: "production",
    git_sha: null,
    image: null,
    deployed_at: null,
    running_count: null,
    desired_count: null,
    pending_count: null,
    status: null,
    commit_url: null,
    author: null,
    author_avatar_url: null,
    message: null,
    pr_url: null,
    committed_at: null,
    ...over,
  };
}

test("IN_PROGRESS is deploying", () => {
  expect(healthOf(svc({ status: "IN_PROGRESS", running_count: 0, desired_count: 2 }))).toBe(
    "deploying",
  );
});

test("pending tasks read as deploying even when rolloutState is null (the bug)", () => {
  // prod-schedule-versioning case: fresh deploy, 0/2 running, tasks launching,
  // rolloutState null because the service has no circuit-breaker rollout tracking.
  expect(
    healthOf(svc({ status: null, running_count: 0, desired_count: 2, pending_count: 2 })),
  ).toBe("deploying");
});

test("understaffed with no pending and no rollout is degraded", () => {
  // Settled but can't hold desired count, nothing launching → genuinely degraded.
  expect(
    healthOf(svc({ status: "COMPLETED", running_count: 1, desired_count: 3, pending_count: 0 })),
  ).toBe("error");
});

test("null status at full count is healthy (not auto-error)", () => {
  expect(
    healthOf(svc({ status: null, running_count: 2, desired_count: 2, pending_count: 0 })),
  ).toBe("healthy");
});

test("FAILED / unavailable / error statuses are degraded", () => {
  expect(healthOf(svc({ status: "FAILED" }))).toBe("error");
  expect(healthOf(svc({ status: "unavailable: MISSING" }))).toBe("error");
  expect(healthOf(svc({ status: "error: KeyError" }))).toBe("error");
});

test("completed at full count is healthy", () => {
  expect(
    healthOf(svc({ status: "COMPLETED", running_count: 3, desired_count: 3 })),
  ).toBe("healthy");
});

test("Amplify RUNNING is deploying", () => {
  expect(healthOf(svc({ platform: "amplify", status: "RUNNING" }))).toBe(
    "deploying",
  );
});

test("Amplify PENDING is deploying", () => {
  expect(healthOf(svc({ platform: "amplify", status: "PENDING" }))).toBe(
    "deploying",
  );
});

test("Amplify CANCELLED is degraded", () => {
  expect(healthOf(svc({ platform: "amplify", status: "CANCELLED" }))).toBe(
    "error",
  );
});

test("Amplify SUCCEED is healthy", () => {
  expect(healthOf(svc({ platform: "amplify", status: "SUCCEED" }))).toBe(
    "healthy",
  );
});

import { expect, test } from "vitest";

import type { DeployedService, DeployRecord } from "@/api";
import { currentDeployRecord, withCurrentDeploy } from "@/lib/deployments";

const svc: DeployedService = {
  name: "wfm-service",
  platform: "ecs",
  env: "production",
  git_sha: "newsha000000",
  image: "123456789012.dkr.ecr.eu-west-1.amazonaws.com/wfm-service:newsha0",
  deployed_at: "2026-05-29T07:00:00Z",
  running_count: 4,
  desired_count: 4,
  pending_count: 0,
  status: "COMPLETED",
  commit_url: "https://github.com/acme/platform/commit/newsha000000",
  author: "bailey",
  author_avatar_url: null,
  message: "ship it",
  pr_url: "https://github.com/acme/platform/pull/4242",
  committed_at: "2026-05-29T04:00:00Z",
};

const olderRecord: DeployRecord = {
  id: 41,
  sha: "oldsha000000",
  image: "img:oldsha0",
  revision: 41,
  registered_at: "2026-05-28T07:00:00Z",
  committed_at: "2026-05-28T04:00:00Z",
  author: "alice",
  author_avatar_url: null,
  message: "previous",
  commit_url: "https://github.com/acme/platform/commit/oldsha000000",
  pr_url: null,
  finished_at: "2026-05-28T07:05:00Z",
};

test("currentDeployRecord maps the live service, marking it live (registered=finished, no revision)", () => {
  const rec = currentDeployRecord(svc);
  expect(rec.sha).toBe("newsha000000");
  expect(rec.revision).toBeNull();
  expect(rec.registered_at).toBe("2026-05-29T07:00:00Z");
  expect(rec.finished_at).toBe("2026-05-29T07:00:00Z");
  expect(rec.message).toBe("ship it");
});

test("prepends the live current deploy when the history fetch lags (sha absent)", () => {
  const merged = withCurrentDeploy([olderRecord], svc);
  expect(merged).toHaveLength(2);
  expect(merged![0].sha).toBe("newsha000000");
  expect(merged![1].sha).toBe("oldsha000000");
});

test("leaves the list untouched when the history fetch already carries the current sha", () => {
  const existing: DeployRecord = { ...olderRecord, sha: "newsha000000", revision: 42 };
  const merged = withCurrentDeploy([existing, olderRecord], svc);
  expect(merged).toHaveLength(2);
  // The richer history record (real revision) is preserved, not clobbered by the synthetic one.
  expect(merged![0].revision).toBe(42);
});

test("synthesizes a single-item list when history hasn't loaded yet", () => {
  const merged = withCurrentDeploy(undefined, svc);
  expect(merged).toHaveLength(1);
  expect(merged![0].sha).toBe("newsha000000");
});

test("passes deployments through untouched when there is no live service", () => {
  expect(withCurrentDeploy([olderRecord], undefined)).toEqual([olderRecord]);
  expect(withCurrentDeploy(undefined, undefined)).toBeUndefined();
});

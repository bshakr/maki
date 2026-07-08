import { screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { renderWithProviders } from "@/test-utils";
import {
  fetchDeployTimeline,
  fetchPullDescription,
  type DeployRecord,
  type DeployTimeline as Timeline,
  type PullDescription,
} from "@/api";

import { DeployDetailSheet } from "./deploy-detail-sheet";

vi.mock("@/api", () => ({
  fetchDeployTimeline: vi.fn(),
  fetchPullDescription: vi.fn(),
}));

const mockTimeline = vi.mocked(fetchDeployTimeline);
const mockPull = vi.mocked(fetchPullDescription);

const deploy: DeployRecord = {
  id: 7,
  sha: "d7e8f9a0b1",
  image: "x",
  revision: 7,
  registered_at: "2026-05-31T07:00:00Z",
  author: "bailey",
  author_avatar_url: "https://avatars.githubusercontent.com/u/2?v=4",
  message: "fix tax calc",
  commit_url: "https://github.com/acme/platform/commit/d7e8f9a0b1",
  pr_url: "https://github.com/acme/platform/pull/4242",
  committed_at: "2026-05-31T04:00:00Z",
  finished_at: "2026-05-31T07:00:00Z",
};

function makeTimeline(): Timeline {
  return {
    service: "wfm-service",
    sha: "d7e8f9a0b1",
    merged_at: null,
    live_at: "2026-05-31T04:05:00Z",
    total_seconds: 300,
    segments: [
      {
        key: "ci:test",
        label: "Test",
        source: "github_actions",
        start: "2026-05-31T04:00:30Z",
        end: "2026-05-31T04:02:00Z",
        seconds: 90,
        status: "success",
        count: 1,
      },
    ],
    generated_at: "2026-05-31T09:00:00Z",
  };
}

const pull: PullDescription = {
  number: 4242,
  title: "feat(wfm): tax calc fix",
  body_excerpt: "This PR corrects the rounding in the tax calculation.",
  url: "https://github.com/acme/platform/pull/4242",
};

beforeEach(() => {
  mockTimeline.mockReset();
  mockPull.mockReset();
  mockTimeline.mockResolvedValue(makeTimeline());
  mockPull.mockResolvedValue(pull);
});

afterEach(() => vi.restoreAllMocks());

test("renders the commit message and a View PR link", async () => {
  renderWithProviders(
    <DeployDetailSheet
      open
      onOpenChange={() => {}}
      service="wfm-service"
      deploy={deploy}
    />,
  );

  expect(await screen.findByText("fix tax calc")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /view pr/i })).toHaveAttribute(
    "href",
    "https://github.com/acme/platform/pull/4242",
  );
});

test("renders the PR excerpt from the mocked fetchPullDescription", async () => {
  renderWithProviders(
    <DeployDetailSheet
      open
      onOpenChange={() => {}}
      service="wfm-service"
      deploy={deploy}
    />,
  );

  await waitFor(() =>
    expect(
      screen.getByText("This PR corrects the rounding in the tax calculation."),
    ).toBeInTheDocument(),
  );
  expect(screen.getByText("feat(wfm): tax calc fix")).toBeInTheDocument();
  expect(mockPull).toHaveBeenCalledWith("wfm-service", 4242);
});

test("shows a live badge when currentSha matches the deploy's sha", async () => {
  renderWithProviders(
    <DeployDetailSheet
      open
      onOpenChange={() => {}}
      service="wfm-service"
      deploy={deploy}
      currentSha="d7e8f9a0b1"
    />,
  );

  expect(await screen.findByText("live")).toBeInTheDocument();
  expect(screen.queryByText("not live")).not.toBeInTheDocument();
});

test("shows a not-live badge when currentSha is absent or mismatched", async () => {
  renderWithProviders(
    <DeployDetailSheet
      open
      onOpenChange={() => {}}
      service="wfm-service"
      deploy={deploy}
      currentSha="0000000000"
    />,
  );

  expect(await screen.findByText("not live")).toBeInTheDocument();
});

test("the embedded timeline requests with the deploy's sha", async () => {
  renderWithProviders(
    <DeployDetailSheet
      open
      onOpenChange={() => {}}
      service="wfm-service"
      deploy={deploy}
    />,
  );

  await waitFor(() => expect(mockTimeline).toHaveBeenCalled());
  expect(mockTimeline).toHaveBeenCalledWith("wfm-service", {
    sha: "d7e8f9a0b1",
    revision: 7,
    mergedAt: "2026-05-31T04:00:00Z",
  });
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { ServiceDetailPage } from "./ServiceDetailPage";

beforeEach(() => window.localStorage.clear());

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

const FULL_IMAGE =
  "123456789012.dkr.ecr.eu-west-1.amazonaws.com/wfm-service:a1b2c3d4e5f6abcdef";

const payload = {
  generated_at: "2026-05-29T09:00:00Z",
  services: [
    { name: "wfm-service", platform: "ecs", env: "production", git_sha: "a1b2c3d4e5f6",
      image: FULL_IMAGE, deployed_at: "2026-05-29T07:00:00Z",
      running_count: 4, desired_count: 4, status: "COMPLETED",
      commit_url: "https://github.com/acme/platform/commit/a1b2c3d4e5f6",
      author: "bailey",
      author_avatar_url: "https://avatars.githubusercontent.com/u/1?v=4",
      message: "ship payroll engine",
      pr_url: "https://github.com/acme/platform/pull/4242",
      committed_at: "2026-05-29T04:00:00Z" },
  ],
};

const deployments = {
  service: "wfm-service",
  generated_at: "2026-05-31T09:00:00Z",
  deployments: [
    { sha: "d7e8f9a0b1", image: "x", revision: 7, registered_at: "2026-05-31T07:00:00Z",
      author: "bailey",
      author_avatar_url: "https://avatars.githubusercontent.com/u/2?v=4",
      message: "fix tax calc",
      commit_url: "https://github.com/acme/platform/commit/d7e8f9a0b1",
      committed_at: "2026-05-31T04:00:00Z", finished_at: "2026-05-31T07:00:00Z" },
    { sha: "9f8e7d6c5b", image: "x", revision: 6, registered_at: "2026-05-30T07:00:00Z",
      author: null, author_avatar_url: null, message: null, commit_url: null,
      committed_at: null, finished_at: null },
  ],
};

function renderAt(path: string) {
  vi.spyOn(global, "fetch").mockImplementation((url) => {
    const u = String(url);
    let body: unknown = payload;
    if (u.includes("/metrics"))
      body = {
        range_days: 30,
        service: "wfm-service",
        deploy_count: 0,
        deploys_per_day: 0,
        lead_time_median_seconds: null,
        lead_time_p90_seconds: null,
        ci_median_seconds: null,
        rollout_median_seconds: null,
        last_deployed_at: null,
        trend: [],
        lead_time_trend: [],
        services: ["wfm-service"],
        generated_at: "2026-05-31T09:00:00Z",
      };
    else if (u.includes("/deployments")) body = deployments;
    else if (u.includes("/deploy-timeline"))
      body = {
        service: "wfm-service",
        sha: null,
        merged_at: null,
        live_at: null,
        total_seconds: null,
        segments: [],
        generated_at: "2026-05-31T09:00:00Z",
      };
    else if (u.includes("/pull"))
      body = {
        number: 4242,
        title: "feat(wfm): tax calc fix",
        body_excerpt: "rounding fix",
        url: "https://github.com/acme/platform/pull/4242",
      };
    else if (u.includes("/rollout"))
      body = {
        service: "wfm-service",
        deployments: [],
        in_progress: false,
        generated_at: "2026-05-31T09:00:00Z",
      };
    return Promise.resolve({ ok: true, json: async () => body } as Response);
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/services/:name" element={<ServiceDetailPage />} />
          <Route
            path="/services/:name/deploys/:sha"
            element={<ServiceDetailPage />}
          />
          <Route path="/services/:name/tasks" element={<ServiceDetailPage />} />
          <Route
            path="/services/:name/metrics"
            element={<ServiceDetailPage />}
          />
          <Route path="/services/:name/env" element={<ServiceDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("renders CURRENT block for a known service with enabled actions", async () => {
  renderAt("/services/wfm-service");
  await waitFor(() => expect(screen.getByText("a1b2c3d")).toBeInTheDocument());
  expect(screen.getByText("4 / 4")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /a1b2c3d/ })).toHaveAttribute(
    "href", "https://github.com/acme/platform/commit/a1b2c3d4e5f6");
  // Logs now open in the in-app drawer (the console link lives inside it).
  expect(screen.getByRole("button", { name: /^logs$/i })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /run task/i })).toBeEnabled();
});

test("the deploy timeline lives behind a single collapsed 'View timeline' trigger", async () => {
  renderAt("/services/wfm-service");
  await waitFor(() => expect(screen.getByText("a1b2c3d")).toBeInTheDocument());

  // Exactly one timeline drill-down (no standalone duplicate), collapsed.
  expect(screen.getAllByText("View timeline")).toHaveLength(1);
  expect(screen.queryByTestId("deploy-timeline")).not.toBeInTheDocument();
});

test("current-deploy shows the merged → live time-to-prod tile", async () => {
  renderAt("/services/wfm-service");
  // committed_at 2026-05-29T04:00 → deployed_at 2026-05-29T07:00 = 3h.
  const tile = await waitFor(() =>
    screen.getByText("Time to prod").closest("div")!,
  );
  expect(within(tile).getByText("3h 0m")).toBeInTheDocument();
  expect(within(tile).getByText("merged → live")).toBeInTheDocument();
});

test("current-deploy surfaces commit message, PR link, and a compact image (not the full ECR URI)", async () => {
  renderAt("/services/wfm-service");
  await waitFor(() =>
    expect(screen.getByText("ship payroll engine")).toBeInTheDocument(),
  );
  // PR link derived from pr_url (#4242).
  expect(screen.getByRole("link", { name: /PR #4242/ })).toHaveAttribute(
    "href", "https://github.com/acme/platform/pull/4242");
  // Compact image: repo + short sha tag.
  expect(screen.getByText("wfm-service:a1b2c3d")).toBeInTheDocument();
  // The long ECR URI is no longer shown verbatim as a visible block.
  expect(screen.queryByText(FULL_IMAGE)).not.toBeInTheDocument();
  // Copy-to-clipboard control is present.
  expect(
    screen.getByRole("button", { name: /copy image uri/i }),
  ).toBeInTheDocument();
});

test("current-deploy shows an author avatar before the commit message", async () => {
  renderAt("/services/wfm-service");
  // Radix Avatar.Image only swaps in the <img> once it loads (jsdom may not
  // fire that), so the queryable element is the alt-labelled image or the
  // initials fallback. Either way the avatar is present in the "What shipped"
  // block, immediately before the headline.
  const headline = await waitFor(() =>
    screen.getByText("ship payroll engine"),
  );
  const row = headline.closest("div")!;
  // Fallback initials for "bailey" -> "BA".
  expect(within(row).getByText("BA")).toBeInTheDocument();
});

test("clicking a row's Roll back opens the dialog targeting that row's deploy", async () => {
  renderAt("/services/wfm-service");
  const region = await screen.findByTestId("deploy-history");

  // The rev 6 row (sha 9f8e7d6c5b) — click its Roll back button.
  const rowButtons = within(region).getAllByRole("button", {
    name: /^roll back$/i,
  });
  // Second row corresponds to rev 6 / sha 9f8e7d6.
  fireEvent.click(rowButtons[1]);

  const dialog = await waitFor(() => screen.getByTestId("rollback-dialog"));
  expect(within(dialog).getByText(/9f8e7d6/)).toBeInTheDocument();
});

test("shows not-found for unknown service", async () => {
  renderAt("/services/ghost");
  await waitFor(() => expect(screen.getByTestId("service-not-found")).toBeInTheDocument());
});

test("renders deploy-history rows", async () => {
  renderAt("/services/wfm-service");
  const region = await screen.findByTestId("deploy-history");

  const shaLink = within(region).getByRole("link", { name: "d7e8f9a" });
  expect(shaLink).toHaveAttribute(
    "href", "https://github.com/acme/platform/commit/d7e8f9a0b1");
  expect(within(region).getByText("bailey")).toBeInTheDocument();
  expect(within(region).getByText("fix tax calc")).toBeInTheDocument();

  // Second row (rev 6) has null author rendered as an em dash.
  expect(within(region).getByText("9f8e7d6")).toBeInTheDocument();
  expect(within(region).getAllByText("—").length).toBeGreaterThan(0);

  // Every history card is a past deploy → tagged "not live".
  expect(within(region).getAllByText("not live").length).toBe(2);
});

test("history rows render author avatars (initials fallback) before the message", async () => {
  renderAt("/services/wfm-service");
  const region = await screen.findByTestId("deploy-history");

  // Rev 7 has author "bailey" + avatar URL → initials fallback "BA".
  expect(within(region).getByText("BA")).toBeInTheDocument();
  // Rev 6 has null author + null avatar → no avatar rendered at all (only one
  // initials fallback across both rows).
  expect(within(region).getAllByText("BA")).toHaveLength(1);
});

test("history row shows merged → live lead time when finished_at is present", async () => {
  renderAt("/services/wfm-service");
  const region = await screen.findByTestId("deploy-history");

  // Rev 7: committed_at 2026-05-31T04:00 → finished_at 2026-05-31T07:00 = 3h.
  const lead = within(region).getByText("3h 0m");
  expect(lead).toBeInTheDocument();
  expect(lead).toHaveAttribute("title", "merged → live");

  // Rev 6 has null finished_at → no lead time appended, and no stray "· —".
  expect(within(region).getByText("9f8e7d6")).toBeInTheDocument();
  expect(within(region).queryByText("· —")).not.toBeInTheDocument();
  // Only one lead-time value in the whole history region (the rev-7 row).
  expect(within(region).getAllByText("3h 0m")).toHaveLength(1);
});

test("clicking a history card's body opens the detail sheet for that row", async () => {
  renderAt("/services/wfm-service");
  const region = await screen.findByTestId("deploy-history");

  // Click the rev-7 row's clickable body (the message lives inside it).
  const body = within(region)
    .getByText("fix tax calc")
    .closest("[role='button']") as HTMLElement;
  fireEvent.click(body);

  const sheet = await waitFor(() => screen.getByTestId("deploy-detail-sheet"));
  expect(within(sheet).getByText("fix tax calc")).toBeInTheDocument();
});

test("deep link to /services/:name/deploys/:sha opens the sheet on load", async () => {
  renderAt("/services/wfm-service/deploys/d7e8f9a");

  const sheet = await waitFor(() => screen.getByTestId("deploy-detail-sheet"));
  expect(within(sheet).getByText("fix tax calc")).toBeInTheDocument();
});

test("deep link to the CURRENT deploy's sha resolves via the merged set, even though the history fetch omits it", async () => {
  // `a1b2c3d` is the live current deploy (in the services payload) but is NOT in the
  // deployments list — the two reads disagree. Reconciling folds the live current into
  // the dataset so the deep link still opens its sheet.
  renderAt("/services/wfm-service/deploys/a1b2c3d");

  const sheet = await waitFor(() => screen.getByTestId("deploy-detail-sheet"));
  expect(within(sheet).getByText("ship payroll engine")).toBeInTheDocument();
});

test("clicking a row's Roll back opens the rollback dialog and NOT the detail sheet", async () => {
  renderAt("/services/wfm-service");
  const region = await screen.findByTestId("deploy-history");

  const rowButtons = within(region).getAllByRole("button", {
    name: /^roll back$/i,
  });
  fireEvent.click(rowButtons[0]);

  await waitFor(() => expect(screen.getByTestId("rollback-dialog")).toBeInTheDocument());
  expect(screen.queryByTestId("deploy-detail-sheet")).not.toBeInTheDocument();
});

test("renders the four service tabs with Deploys active by default", async () => {
  renderAt("/services/wfm-service");
  await screen.findByRole("tab", { name: "Deploys" });
  for (const label of ["Deploys", "Tasks", "Metrics", "Env"]) {
    expect(screen.getByRole("tab", { name: label })).toBeInTheDocument();
  }
  expect(screen.getByRole("tab", { name: "Deploys" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
});

test("clicking the Tasks tab navigates and swaps content away from Deploys", async () => {
  renderAt("/services/wfm-service");
  await waitFor(() => expect(screen.getByText("4 / 4")).toBeInTheDocument());

  fireEvent.click(screen.getByRole("tab", { name: "Tasks" }));

  await waitFor(() =>
    expect(screen.getByRole("tab", { name: "Tasks" })).toHaveAttribute(
      "aria-selected",
      "true",
    ),
  );
  // Deploys content (the current-deploy task count) is gone; the Tasks placeholder shows.
  expect(screen.queryByText("4 / 4")).not.toBeInTheDocument();
  expect(screen.getByText("Coming next.")).toBeInTheDocument();
});

test("deep link to /services/:name/metrics opens on the Metrics tab", async () => {
  renderAt("/services/wfm-service/metrics");
  const metricsTab = await screen.findByRole("tab", { name: "Metrics" });
  expect(metricsTab).toHaveAttribute("aria-selected", "true");
  expect(screen.queryByText("4 / 4")).not.toBeInTheDocument();
});

test("the deploy-detail deep link keeps the Deploys tab active", async () => {
  renderAt("/services/wfm-service/deploys/d7e8f9a");
  await waitFor(() => screen.getByTestId("deploy-detail-sheet"));
  // The sheet is a modal, so it marks the background (incl. the tab bar) aria-hidden;
  // query with hidden:true to reach the still-selected Deploys tab behind it.
  expect(
    await screen.findByRole("tab", { name: "Deploys", hidden: true }),
  ).toHaveAttribute("aria-selected", "true");
});

// --- shared status treatment + Load-more pagination -------------------------

// A deployments payload whose two history rows carry rollback / failed status, and a
// `next_cursor` so the page offers "Load more". The custom fetch responds with this on page 1
// and an older page (no further cursor) when the cursor query param is present.
function renderWithStatusAndPaging() {
  vi.spyOn(global, "fetch").mockImplementation((url) => {
    const u = String(url);
    if (u.includes("/rollout")) {
      return Promise.resolve({
        ok: true,
        json: async () => ({
          service: "wfm-service",
          deployments: [],
          in_progress: false,
          generated_at: "2026-05-31T09:00:00Z",
        }),
      } as Response);
    }
    if (u.includes("/services") && !u.includes("/deployments")) {
      return Promise.resolve({ ok: true, json: async () => payload } as Response);
    }
    if (u.includes("/deployments")) {
      const hasCursor = u.includes("cursor=");
      const body = hasCursor
        ? {
            service: "wfm-service",
            generated_at: "2026-05-31T09:00:00Z",
            next_cursor: null,
            deployments: [
              {
                sha: "older1234x",
                image: "x",
                revision: 5,
                registered_at: "2026-05-29T07:00:00Z",
                author: "bailey",
                author_avatar_url: null,
                message: "older deploy",
                commit_url: null,
                committed_at: null,
                finished_at: null,
                status: "success",
                is_rollback: false,
              },
            ],
          }
        : {
            service: "wfm-service",
            generated_at: "2026-05-31T09:00:00Z",
            next_cursor: "Y3Vyc29y",
            deployments: [
              {
                sha: "d7e8f9a0b1",
                image: "x",
                revision: 7,
                registered_at: "2026-05-31T07:00:00Z",
                author: "bailey",
                author_avatar_url: null,
                message: "rolled back tax calc",
                commit_url: null,
                committed_at: null,
                finished_at: null,
                status: "success",
                is_rollback: true,
              },
              {
                sha: "9f8e7d6c5b",
                image: "x",
                revision: 6,
                registered_at: "2026-05-30T07:00:00Z",
                author: null,
                author_avatar_url: null,
                message: "broke prod",
                commit_url: null,
                committed_at: null,
                finished_at: null,
                status: "failed",
                is_rollback: false,
              },
            ],
          };
      return Promise.resolve({ ok: true, json: async () => body } as Response);
    }
    return Promise.resolve({ ok: true, json: async () => ({}) } as Response);
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/services/wfm-service"]}>
        <Routes>
          <Route path="/services/:name" element={<ServiceDetailPage />} />
          <Route
            path="/services/:name/deploys/:sha"
            element={<ServiceDetailPage />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("history rows surface rollback + failed status markers", async () => {
  renderWithStatusAndPaging();
  const region = await screen.findByTestId("deploy-history");

  // The rollback row carries the rollback marker + the coloured rollback edge.
  expect(within(region).getByText("rollback")).toBeInTheDocument();
  const rollbackRow = within(region)
    .getByText("rolled back tax calc")
    .closest("[data-state]") as HTMLElement;
  expect(rollbackRow).toHaveAttribute("data-state", "rollback");

  // The failed row carries the failed marker + the failed edge.
  expect(within(region).getByText("failed")).toBeInTheDocument();
  const failedRow = within(region)
    .getByText("broke prod")
    .closest("[data-state]") as HTMLElement;
  expect(failedRow).toHaveAttribute("data-state", "failed");
});

test("Load more appends the next (older) page and then disappears", async () => {
  renderWithStatusAndPaging();
  const region = await screen.findByTestId("deploy-history");

  // Page 1 offers Load more (next_cursor present); the older deploy isn't shown yet.
  const loadMore = within(region).getByRole("button", { name: /load more/i });
  expect(within(region).queryByText("older deploy")).not.toBeInTheDocument();

  fireEvent.click(loadMore);

  // The older page is appended...
  await waitFor(() =>
    expect(within(region).getByText("older deploy")).toBeInTheDocument(),
  );
  // ...and with no further cursor, Load more is gone.
  expect(
    within(region).queryByRole("button", { name: /load more/i }),
  ).not.toBeInTheDocument();
});

test("deep link to a sha NOT in the loaded list fetches the single deploy and opens the sheet", async () => {
  // `0ldsha1` is a slowest/fastest-style deep link: it's absent from both the services payload and
  // the deployments page, so the in-list fast path resolves nothing. The page must fall back to the
  // single-deploy endpoint and open the sheet for it.
  const single = {
    id: 99,
    sha: "0ldsha1deadbeef",
    image: "x",
    revision: 3,
    registered_at: "2026-01-02T07:00:00Z",
    author: "old-author",
    author_avatar_url: null,
    message: "ancient slow deploy",
    commit_url: null,
    pr_url: null,
    committed_at: null,
    finished_at: null,
    status: "success",
    is_rollback: false,
  };
  const singleSpy = vi.fn();
  vi.spyOn(global, "fetch").mockImplementation((url) => {
    const u = String(url);
    if (/\/deploys\/[^/?]+/.test(u)) {
      singleSpy(u);
      return Promise.resolve({ ok: true, json: async () => single } as Response);
    }
    let body: unknown = payload;
    if (u.includes("/metrics"))
      body = {
        range_days: 30, service: "wfm-service", deploy_count: 0, deploys_per_day: 0,
        lead_time_median_seconds: null, lead_time_p90_seconds: null, ci_median_seconds: null,
        rollout_median_seconds: null, last_deployed_at: null, trend: [], lead_time_trend: [],
        services: ["wfm-service"], generated_at: "2026-05-31T09:00:00Z",
      };
    else if (u.includes("/deployments")) body = deployments;
    else if (u.includes("/rollout"))
      body = {
        service: "wfm-service",
        deployments: [],
        in_progress: false,
        generated_at: "2026-05-31T09:00:00Z",
      };
    return Promise.resolve({ ok: true, json: async () => body } as Response);
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/services/wfm-service/deploys/0ldsha1"]}>
        <Routes>
          <Route path="/services/:name" element={<ServiceDetailPage />} />
          <Route
            path="/services/:name/deploys/:sha"
            element={<ServiceDetailPage />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );

  const sheet = await waitFor(() => screen.getByTestId("deploy-detail-sheet"));
  expect(within(sheet).getByText("ancient slow deploy")).toBeInTheDocument();
  expect(singleSpy).toHaveBeenCalledWith(
    expect.stringContaining("/services/wfm-service/deploys/0ldsha1"),
  );
});

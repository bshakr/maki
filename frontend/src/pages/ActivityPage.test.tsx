import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { renderWithProviders } from "@/test-utils";

import { ActivityPage } from "./ActivityPage";

afterEach(() => vi.restoreAllMocks());

beforeEach(() => {
  // jsdom has no layout; stub scrollIntoView so the jump effect doesn't throw.
  Element.prototype.scrollIntoView = vi.fn();
});

const payload = {
  generated_at: "2026-05-31T09:00:00Z",
  next_cursor: null,
  items: [
    { id: 1, service: "wfm-service", platform: "ecs", sha: "a1b2c3d4e5", deployed_at: "2026-05-31T08:00:00Z",
      status: "COMPLETED", author: "bailey",
      author_avatar_url: "https://avatars.githubusercontent.com/u/1?v=4",
      message: "ship payroll engine",
      commit_url: "https://github.com/acme/platform/commit/a1b2c3d4e5",
      pr_url: "https://github.com/acme/platform/pull/4242",
      committed_at: "2026-05-31T05:00:00Z" },
    { id: 2, service: "inventory", platform: "ecs", sha: "9f8e7d6c5b", deployed_at: "2026-05-31T07:00:00Z",
      status: "IN_PROGRESS", author: null, author_avatar_url: null, message: null,
      commit_url: null, pr_url: null, committed_at: null },
  ],
};

function renderPage() {
  vi.spyOn(global, "fetch").mockResolvedValue({ ok: true, json: async () => payload } as Response);
  return renderWithProviders(<ActivityPage />, { route: "/activity" });
}

test("renders deploy cards that deep-link to the deploy sheet on the service page", async () => {
  renderPage();
  await waitFor(() => expect(screen.getByText("wfm-service")).toBeInTheDocument());
  // The whole card links to that deploy's sheet URL (short sha).
  expect(screen.getByRole("link", { name: /wfm-service/ })).toHaveAttribute(
    "href", "/services/wfm-service/deploys/a1b2c3d");
  // Rich content: commit message + author surface on the card.
  expect(screen.getByText("ship payroll engine")).toBeInTheDocument();
  expect(screen.getByText("bailey")).toBeInTheDocument();
});

test("live tail console shows the LIVE indicator and a Pause control by default", async () => {
  renderPage();
  await waitFor(() => expect(screen.getByText("wfm-service")).toBeInTheDocument());

  // Header reads LIVE while tailing; the toggle offers Pause.
  expect(screen.getByTestId("live-indicator")).toHaveTextContent(/LIVE/);
  const toggle = screen.getByTestId("live-toggle");
  expect(toggle).toHaveTextContent(/Pause/);
  expect(toggle).toHaveAttribute("aria-pressed", "false");
  // While tailing, polling handles freshness — no manual refresh button is shown.
  expect(
    screen.queryByRole("button", { name: /refresh now/i }),
  ).not.toBeInTheDocument();
});

test("Pause toggles the live tail off (and exposes a manual refresh), Resume turns it back on", async () => {
  renderPage();
  await waitFor(() => expect(screen.getByText("wfm-service")).toBeInTheDocument());

  const toggle = screen.getByTestId("live-toggle");

  // Pause: label flips to Resume, indicator reads PAUSED, manual refresh appears.
  fireEvent.click(toggle);
  await waitFor(() =>
    expect(screen.getByTestId("live-toggle")).toHaveTextContent(/Resume/),
  );
  expect(screen.getByTestId("live-indicator")).toHaveTextContent(/PAUSED/);
  expect(screen.getByTestId("live-toggle")).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  // A manual refresh affordance is available while paused so investigation
  // isn't stuck on stale data.
  const refresh = screen.getByRole("button", { name: /refresh now/i });
  fireEvent.click(refresh);

  // Resume: back to LIVE.
  fireEvent.click(screen.getByTestId("live-toggle"));
  await waitFor(() =>
    expect(screen.getByTestId("live-toggle")).toHaveTextContent(/Pause/),
  );
  expect(screen.getByTestId("live-indicator")).toHaveTextContent(/LIVE/);
});

test("multiselect filter narrows the feed to the selected service", async () => {
  renderPage();
  await waitFor(() => expect(screen.getByText("wfm-service")).toBeInTheDocument());

  // Trigger starts at "All services" with both deploys visible.
  const trigger = screen.getByTestId("service-filter-trigger");
  expect(trigger).toHaveTextContent("All services");
  expect(screen.getByText("inventory")).toBeInTheDocument();

  // Both services have feed cards (links) before filtering.
  expect(screen.getByRole("link", { name: /wfm-service/ })).toBeInTheDocument();

  // Open the dropdown and tick "inventory" — the feed narrows to just it.
  fireEvent.click(trigger);
  const option = await screen.findByRole("option", { name: /inventory/i });
  fireEvent.click(option);

  // The wfm-service feed card is gone (its link), while inventory remains.
  // (The dropdown list still lists every option, so we assert on the card link.)
  await waitFor(() =>
    expect(
      screen.queryByRole("link", { name: /wfm-service/ }),
    ).not.toBeInTheDocument(),
  );
  expect(screen.getByRole("link", { name: /inventory/ })).toBeInTheDocument();
  // Trigger now reflects the single selection.
  expect(trigger).toHaveTextContent("inventory");
});

// A windowed payload: two deploys straddling the target moment (07:30Z).
const aroundPayload = {
  generated_at: "2026-05-31T09:00:00Z",
  next_cursor: null,
  items: [
    { id: 10, service: "after-svc", platform: "ecs", sha: "aaaa111", deployed_at: "2026-05-31T08:00:00Z",
      status: null, author: "bailey", author_avatar_url: null, message: "deploy after target",
      commit_url: null, pr_url: null, committed_at: null },
    { id: 11, service: "before-svc", platform: "ecs", sha: "bbbb222", deployed_at: "2026-05-31T07:00:00Z",
      status: null, author: "bailey", author_avatar_url: null, message: "deploy before target",
      commit_url: null, pr_url: null, committed_at: null },
  ],
};

test("jump fetches the window around the picked timestamp and shows the marker", async () => {
  const fetchMock = vi.spyOn(global, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    const body = url.includes("around=") ? aroundPayload : payload;
    return { ok: true, json: async () => body } as Response;
  });

  renderWithProviders(<ActivityPage />, { route: "/activity" });
  await waitFor(() => expect(screen.getByText("wfm-service")).toBeInTheDocument());

  // Open the picker popover and hit Jump (defaults to "now").
  fireEvent.click(screen.getByTestId("datetime-trigger"));
  fireEvent.click(await screen.findByTestId("datetime-jump"));

  // The marker line renders and a windowed request was issued with around= + a fixed window.
  await waitFor(() => expect(screen.getByTestId("jump-marker")).toBeInTheDocument());
  expect(screen.getByText("deploy after target")).toBeInTheDocument();
  expect(screen.getByText("deploy before target")).toBeInTheDocument();
  const calledAround = fetchMock.mock.calls.some(([u]) =>
    /\/api\/activity\?.*around=.*window=6/.test(String(u)),
  );
  expect(calledAround).toBe(true);
});

test("jumping freezes the live tail and Back to latest resumes it", async () => {
  vi.spyOn(global, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    const body = url.includes("around=") ? aroundPayload : payload;
    return { ok: true, json: async () => body } as Response;
  });

  renderWithProviders(<ActivityPage />, { route: "/activity" });
  await waitFor(() => expect(screen.getByText("wfm-service")).toBeInTheDocument());
  expect(screen.getByTestId("live-indicator")).toHaveTextContent(/LIVE/);

  // Jump: the indicator freezes and the Pause toggle is replaced by Back to latest.
  fireEvent.click(screen.getByTestId("datetime-trigger"));
  fireEvent.click(await screen.findByTestId("datetime-jump"));
  await waitFor(() => expect(screen.getByTestId("jump-marker")).toBeInTheDocument());
  expect(screen.getByTestId("live-indicator")).toHaveTextContent(/FROZEN/);
  expect(screen.queryByTestId("live-toggle")).not.toBeInTheDocument();
  expect(screen.getByText(/showing deploys around/i)).toBeInTheDocument();

  // Back to latest: returns to the live edge and re-enables tailing.
  fireEvent.click(screen.getByRole("button", { name: /clear jump/i }));
  await waitFor(() =>
    expect(screen.queryByTestId("jump-marker")).not.toBeInTheDocument(),
  );
  expect(screen.getByTestId("live-indicator")).toHaveTextContent(/LIVE/);
  expect(screen.getByTestId("live-toggle")).toHaveTextContent(/Pause/);
});

test("empty window shows a graceful empty state", async () => {
  const empty = { generated_at: "2026-05-31T09:00:00Z", next_cursor: null, items: [] };
  vi.spyOn(global, "fetch").mockImplementation(async (input) =>
    ({ ok: true, json: async () => (String(input).includes("around=") ? empty : payload) }) as Response,
  );

  renderWithProviders(<ActivityPage />, { route: "/activity" });
  await waitFor(() => expect(screen.getByText("wfm-service")).toBeInTheDocument());

  fireEvent.click(screen.getByTestId("datetime-trigger"));
  fireEvent.click(await screen.findByTestId("datetime-jump"));

  await waitFor(() => expect(screen.getByText(/no deploys around/i)).toBeInTheDocument());
});

// Page 1 carries a cursor; page 2 is the older tail with no further cursor.
const page1 = {
  generated_at: "2026-05-31T09:00:00Z",
  next_cursor: "Y3Vyc29yLXAx",
  items: [
    { id: 20, service: "page1-svc", platform: "ecs", sha: "1111aaa", deployed_at: "2026-05-31T08:00:00Z",
      status: null, author: null, author_avatar_url: null, message: null,
      commit_url: null, pr_url: null, committed_at: null },
  ],
};
const page2 = {
  generated_at: "2026-05-31T09:00:01Z",
  next_cursor: null,
  items: [
    { id: 21, service: "page2-svc", platform: "ecs", sha: "2222bbb", deployed_at: "2026-05-31T06:00:00Z",
      status: null, author: null, author_avatar_url: null, message: null,
      commit_url: null, pr_url: null, committed_at: null },
  ],
};

test("Load more issues a cursor request and appends the next page", async () => {
  const fetchMock = vi.spyOn(global, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    const body = url.includes("cursor=") ? page2 : page1;
    return { ok: true, json: async () => body } as Response;
  });

  renderWithProviders(<ActivityPage />, { route: "/activity" });
  await waitFor(() => expect(screen.getByText("page1-svc")).toBeInTheDocument());

  // First page rendered; Load more is available because next_cursor is set.
  const loadMore = screen.getByRole("button", { name: /load more/i });
  fireEvent.click(loadMore);

  // The next page appends below the first; the cursor from page 1 was sent.
  await waitFor(() => expect(screen.getByText("page2-svc")).toBeInTheDocument());
  expect(screen.getByText("page1-svc")).toBeInTheDocument(); // page 1 still present
  const calledWithCursor = fetchMock.mock.calls.some(([u]) =>
    /\/api\/activity\?.*cursor=Y3Vyc29yLXAx/.test(String(u)),
  );
  expect(calledWithCursor).toBe(true);

  // page 2 has no next_cursor -> Load more disappears.
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: /load more/i })).not.toBeInTheDocument(),
  );
});

test("Load more is hidden when the first page has no next_cursor", async () => {
  // `payload` has next_cursor: null.
  renderPage();
  await waitFor(() => expect(screen.getByText("wfm-service")).toBeInTheDocument());
  expect(screen.queryByRole("button", { name: /load more/i })).not.toBeInTheDocument();
});

test("Load more is hidden in jump mode even when a cursor exists", async () => {
  vi.spyOn(global, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    const body = url.includes("around=") ? aroundPayload : page1; // page1 has a next_cursor
    return { ok: true, json: async () => body } as Response;
  });

  renderWithProviders(<ActivityPage />, { route: "/activity" });
  await waitFor(() => expect(screen.getByText("page1-svc")).toBeInTheDocument());
  // Latest feed has a cursor, so Load more is visible here.
  expect(screen.getByRole("button", { name: /load more/i })).toBeInTheDocument();

  // Jump: the windowed path is not paginated -> Load more must disappear.
  fireEvent.click(screen.getByTestId("datetime-trigger"));
  fireEvent.click(await screen.findByTestId("datetime-jump"));
  await waitFor(() => expect(screen.getByTestId("jump-marker")).toBeInTheDocument());
  expect(screen.queryByRole("button", { name: /load more/i })).not.toBeInTheDocument();
});

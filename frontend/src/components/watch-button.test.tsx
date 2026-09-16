import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { WatchButton } from "./watch-button";
import { renderWithProviders } from "@/test-utils";

afterEach(() => vi.restoreAllMocks());

// Stateful stand-in for /api/watches so a toggle really round-trips: the POST/DELETE mutates the
// set the following GET reads back, which is what keeps the two placements in sync.
function mockWatches(initial: string[] = []) {
  const watched = new Set(initial);
  return vi.spyOn(global, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    if (method === "GET") {
      return Response.json({
        watches: [...watched].map((service) => ({
          service,
          created_at: "2026-09-16T00:00:00Z",
        })),
      });
    }
    if (method === "POST") {
      const { service } = JSON.parse(String(init?.body));
      watched.add(service);
      return Response.json({ service, created_at: "2026-09-16T00:00:00Z" }, { status: 201 });
    }
    watched.delete(decodeURIComponent(url.split("/").pop()!));
    return new Response(null, { status: 204 });
  });
}

test("renders unwatched, and labels the action for screen readers", async () => {
  mockWatches();
  renderWithProviders(<WatchButton name="insights" />);

  await waitFor(() =>
    expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "false"),
  );
  expect(screen.getByRole("button")).toHaveAccessibleName(
    "Notify me about insights deploys",
  );
});

test("renders pressed when the service is already watched", async () => {
  mockWatches(["insights"]);
  renderWithProviders(<WatchButton name="insights" />);

  await waitFor(() =>
    expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "true"),
  );
  expect(screen.getByRole("button")).toHaveAccessibleName(
    "Stop notifying me about insights deploys",
  );
});

test("POSTs the service and reflects the new state", async () => {
  const fetchSpy = mockWatches();
  renderWithProviders(<WatchButton name="insights" />);
  await waitFor(() =>
    expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "false"),
  );

  fireEvent.click(screen.getByRole("button"));

  await waitFor(() =>
    expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "true"),
  );
  const posted = fetchSpy.mock.calls.find(([, init]) => init?.method === "POST");
  expect(JSON.parse(String(posted?.[1]?.body))).toEqual({ service: "insights" });
});

test("DELETEs the service when toggled off", async () => {
  const fetchSpy = mockWatches(["billing service"]);
  renderWithProviders(<WatchButton name="billing service" />);
  await waitFor(() =>
    expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "true"),
  );

  fireEvent.click(screen.getByRole("button"));

  await waitFor(() =>
    expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "false"),
  );
  const deleted = fetchSpy.mock.calls.find(([, init]) => init?.method === "DELETE");
  expect(String(deleted?.[0])).toBe("/api/watches/billing%20service");
});

test("keeps the true state when the write fails", async () => {
  vi.spyOn(global, "fetch").mockImplementation(async (_input, init) => {
    if ((init?.method ?? "GET") === "GET") return Response.json({ watches: [] });
    return Response.json({ detail: "unknown service" }, { status: 404 });
  });
  renderWithProviders(<WatchButton name="ghost" />);
  await waitFor(() =>
    expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "false"),
  );

  fireEvent.click(screen.getByRole("button"));

  await waitFor(() =>
    expect(screen.getByRole("button")).toHaveAttribute(
      "title",
      "Couldn't update notifications — try again",
    ),
  );
  expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "false");
});

// Same as mockWatches, but the write parks on a gate so the in-flight window can be inspected.
function gatedWatches() {
  const watched = new Set<string>();
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => (release = resolve));
  const fetchSpy = vi.spyOn(global, "fetch").mockImplementation(async (_input, init) => {
    if ((init?.method ?? "GET") === "GET") {
      return Response.json({
        watches: [...watched].map((service) => ({
          service,
          created_at: "2026-09-16T00:00:00Z",
        })),
      });
    }
    await gate;
    const { service } = JSON.parse(String(init?.body));
    watched.add(service);
    return Response.json({ service, created_at: "2026-09-16T00:00:00Z" }, { status: 201 });
  });
  return { fetchSpy, release: () => release() };
}

test("stays enabled and focused while the write is in flight", async () => {
  const { release } = gatedWatches();
  renderWithProviders(<WatchButton name="insights" />);
  await waitFor(() =>
    expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "false"),
  );

  const btn = screen.getByRole("button");
  btn.focus();
  fireEvent.click(btn);

  // `disabled` is what the assertions below really guard: a real browser blurs a disabled element
  // (jsdom does not), and screen readers skip it, so the busy state is carried by aria-busy alone.
  await waitFor(() => expect(btn).toHaveAttribute("aria-busy", "true"));
  expect(btn).toBeEnabled();
  expect(document.activeElement).toBe(btn);

  release();
  await waitFor(() => expect(btn).toHaveAttribute("aria-pressed", "true"));
  expect(btn).toBeEnabled();
  expect(document.activeElement).toBe(btn);
});

test("ignores a repeat click while the write is in flight", async () => {
  const { fetchSpy, release } = gatedWatches();
  renderWithProviders(<WatchButton name="insights" />);
  await waitFor(() =>
    expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "false"),
  );

  const btn = screen.getByRole("button");
  fireEvent.click(btn);
  await waitFor(() => expect(btn).toHaveAttribute("aria-busy", "true"));
  fireEvent.click(btn);

  release();
  await waitFor(() => expect(btn).toHaveAttribute("aria-pressed", "true"));
  expect(fetchSpy.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
});

test("stops click propagation when nested in a clickable parent", async () => {
  mockWatches();
  let parentClicked = false;
  renderWithProviders(
    <div onClick={() => (parentClicked = true)}>
      <WatchButton name="insights" />
    </div>,
  );
  await waitFor(() =>
    expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "false"),
  );

  fireEvent.click(screen.getByRole("button"));

  expect(parentClicked).toBe(false);
  await waitFor(() =>
    expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "true"),
  );
});

test("does not stop propagation when stopPropagation is false", async () => {
  mockWatches();
  let parentClicked = false;
  renderWithProviders(
    <div onClick={() => (parentClicked = true)}>
      <WatchButton name="insights" stopPropagation={false} />
    </div>,
  );
  await waitFor(() =>
    expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "false"),
  );

  fireEvent.click(screen.getByRole("button"));

  expect(parentClicked).toBe(true);
});

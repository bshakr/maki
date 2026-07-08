import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { renderWithProviders } from "@/test-utils";
import { type ServiceLogsResponse } from "@/api";
import { cloudWatchLogsUrlForGroup } from "@/lib/aws-console";

import { LogsSheet } from "./logs-sheet";

const CONSOLE_URL =
  "https://eu-west-1.console.aws.amazon.com/cloudwatch/home?region=eu-west-1#logsV2:log-groups";

// Once the logs response lands, the in-sheet console link is rebuilt from the resolved group
// (not the convention-based `consoleUrl` prop). For the default body that's this deep-link.
const RESOLVED_URL = cloudWatchLogsUrlForGroup(
  "/ecs/wfm-service-production",
  "eu-west-1",
  "eu-west-1",
);

function body(over: Partial<ServiceLogsResponse> = {}): ServiceLogsResponse {
  return {
    log_group: "/ecs/wfm-service-production",
    region: "eu-west-1",
    truncated: false,
    error: null,
    events: [
      { timestamp: "2026-06-05T11:58:00Z", message: "starting up", stream: "s1" },
      { timestamp: "2026-06-05T11:59:00Z", message: "ERROR boom failed", stream: "s1" },
    ],
    ...over,
  };
}

// Drive the real fetchServiceLogs (incl. ensureOk's 503 → AwsCredentialsError) by stubbing fetch,
// matching the nav-user creds test pattern. This keeps react-query's rejection handling in its own
// controlled flow (no floating rejected promise flagged as unhandled).
function mockFetch(resp: Partial<Response> & { status: number; ok: boolean }) {
  return vi.spyOn(global, "fetch").mockResolvedValue(resp as Response);
}

function okResponse(over: Partial<ServiceLogsResponse> = {}) {
  return { ok: true, status: 200, json: async () => body(over) };
}

function renderSheet() {
  return renderWithProviders(
    <LogsSheet
      open
      onOpenChange={() => {}}
      service="wfm-service"
      consoleUrl={CONSOLE_URL}
    />,
  );
}

beforeEach(() => vi.restoreAllMocks());
afterEach(() => vi.restoreAllMocks());

test("renders the tailed log events", async () => {
  mockFetch(okResponse());
  renderSheet();

  expect(await screen.findByText("starting up")).toBeInTheDocument();
  expect(screen.getByText("ERROR boom failed")).toBeInTheDocument();
  expect(screen.getByText("/ecs/wfm-service-production")).toBeInTheDocument();
});

test("highlights an ERROR line with the destructive tint", async () => {
  mockFetch(okResponse());
  renderSheet();

  const errLine = await screen.findByText("ERROR boom failed");
  expect(errLine.className).toContain("text-destructive");
  expect(screen.getByText("starting up").className).not.toContain("text-destructive");
});

test("empty result shows the empty state + console fallback", async () => {
  mockFetch(okResponse({ events: [] }));
  renderSheet();

  expect(await screen.findByText("No recent log events")).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: /open in aws console/i }),
  ).toHaveAttribute("href", RESOLVED_URL);
});

test("not_found shows the no-log-group message + console fallback", async () => {
  mockFetch(okResponse({ events: [], error: "not_found" }));
  renderSheet();

  expect(await screen.findByText("No log group")).toBeInTheDocument();
  // The link is rebuilt from the resolved group once the response lands.
  expect(
    screen.getByRole("link", { name: /open in aws console/i }),
  ).toHaveAttribute("href", RESOLVED_URL);
});

test("console link uses the resolved log group once loaded, not the convention", async () => {
  // A non-convention group (the bug case): the link must point at the resolved group.
  mockFetch(
    okResponse({ events: [], error: "not_found", log_group: "/ecs/custom-real", region: "us-east-1" }),
  );
  renderSheet();

  const link = await screen.findByRole("link", { name: /open in aws console/i });
  expect(link).toHaveAttribute(
    "href",
    expect.stringContaining("$252Fecs$252Fcustom-real"),
  );
  expect(link.getAttribute("href")).toContain("region=us-east-1");
  // Not the convention-based prop URL.
  expect(link).not.toHaveAttribute("href", CONSOLE_URL);
});

test("forbidden shows the IAM message + console fallback", async () => {
  mockFetch(okResponse({ events: [], error: "forbidden" }));
  renderSheet();

  expect(await screen.findByText(/can't read these logs/i)).toBeInTheDocument();
  expect(screen.getByText(/logs:FilterLogEvents/i)).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: /open in aws console/i }),
  ).toBeInTheDocument();
});

test("a 503 creds error renders the re-assume affordance", async () => {
  mockFetch({
    ok: false,
    status: 503,
    json: async () => ({ error: "aws_credentials_unavailable", detail: "x" }),
  });
  renderSheet();

  expect(
    await screen.findByText(/AWS credentials missing or expired/i),
  ).toBeInTheDocument();
});

test("auto-refresh toggle flips its label and aria-pressed", async () => {
  mockFetch(okResponse());
  renderSheet();
  await screen.findByText("starting up");

  const toggle = screen.getByRole("button", { name: /auto-refresh/i });
  expect(toggle).toHaveAttribute("aria-pressed", "false");

  fireEvent.click(toggle);
  expect(toggle).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: /auto-refresh on/i })).toBeInTheDocument();
});

test("manual refresh refetches the logs", async () => {
  const spy = mockFetch(okResponse());
  renderSheet();
  await screen.findByText("starting up");

  expect(spy).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: /^refresh$/i }));
  await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
});

import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { RunTaskSheet } from "./run-task-sheet";
import { renderWithProviders } from "@/test-utils";
import { runTaskPreview } from "@/api";

vi.mock("@/api", () => ({
  runTaskPreview: vi.fn(),
}));

const mockedRunTaskPreview = vi.mocked(runTaskPreview);

afterEach(() => vi.clearAllMocks());

function renderSheet() {
  return renderWithProviders(
    <RunTaskSheet
      open
      onOpenChange={() => {}}
      service="wfm-service"
      taskDef={null}
    />,
  );
}

test("renders title, PREVIEW badge and the preview-only warning", () => {
  renderSheet();
  expect(screen.getByText("Run task · wfm-service")).toBeInTheDocument();
  expect(screen.getByText("PREVIEW")).toBeInTheDocument();
  expect(screen.getByText("Preview only")).toBeInTheDocument();
  expect(
    screen.getByText(/Nothing runs in production/i),
  ).toBeInTheDocument();
});

test("Preview run is disabled until the service name is typed AND a command is entered", () => {
  renderSheet();

  const button = screen.getByRole("button", { name: /preview run/i });
  expect(button).toBeDisabled();

  // Command alone — still disabled.
  fireEvent.change(screen.getByLabelText(/^Command$/i), {
    target: { value: "python -m scripts.backfill" },
  });
  expect(button).toBeDisabled();

  // Name alone (clear command) — still disabled.
  fireEvent.change(screen.getByLabelText(/^Command$/i), {
    target: { value: "" },
  });
  fireEvent.change(screen.getByLabelText(/to confirm/i), {
    target: { value: "wfm-service" },
  });
  expect(button).toBeDisabled();

  // Both set — enabled.
  fireEvent.change(screen.getByLabelText(/^Command$/i), {
    target: { value: "python -m scripts.backfill" },
  });
  expect(button).toBeEnabled();
});

test("clicking Preview run calls runTaskPreview with the typed command and renders the result", async () => {
  mockedRunTaskPreview.mockResolvedValue({
    service: "wfm-service",
    command: "python -m scripts.backfill --since 2026-05-01",
    task_def: null,
    executed: false,
    message:
      "Preview only — run-task execution is not implemented. No production change was made.",
  });

  renderSheet();

  fireEvent.change(screen.getByLabelText(/^Command$/i), {
    target: { value: "python -m scripts.backfill --since 2026-05-01" },
  });
  fireEvent.change(screen.getByLabelText(/to confirm/i), {
    target: { value: "wfm-service" },
  });
  fireEvent.click(screen.getByRole("button", { name: /preview run/i }));

  await waitFor(() =>
    expect(screen.getByTestId("run-task-result")).toBeInTheDocument(),
  );

  expect(mockedRunTaskPreview).toHaveBeenCalledTimes(1);
  expect(mockedRunTaskPreview).toHaveBeenCalledWith(
    "wfm-service",
    "python -m scripts.backfill --since 2026-05-01",
    null,
  );

  expect(
    screen.getByText("Preview only — no production change was made."),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/run-task execution is not implemented/i),
  ).toBeInTheDocument();
});

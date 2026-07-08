import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { RollbackDialog } from "./rollback-dialog";
import type { DeployRecord } from "@/api";

afterEach(() => vi.restoreAllMocks());

const target: DeployRecord = {
  id: 7,
  sha: "d7e8f9a0b1",
  image: "x",
  revision: 7,
  registered_at: "2026-05-31T07:00:00Z",
  author: "bailey",
  message: "fix tax calc",
  commit_url: "https://github.com/acme/platform/commit/d7e8f9a0b1",
  pr_url: "https://github.com/acme/platform/pull/7412",
};

function renderDialog(props?: { target?: DeployRecord | null }) {
  return render(
    <RollbackDialog
      open
      onOpenChange={() => {}}
      service="wfm-service"
      currentSha="a1b2c3d4e5f6"
      target={props?.target === undefined ? target : props.target}
    />,
  );
}

test("renders the PREVIEW warning text", () => {
  renderDialog();
  expect(screen.getByText("Preview only")).toBeInTheDocument();
  expect(
    screen.getByText(/does not change production/i),
  ).toBeInTheDocument();
  expect(screen.getByText("PREVIEW")).toBeInTheDocument();
});

test("shows the fixed target deploy and no target selector", () => {
  renderDialog();
  // Fixed target: short sha is shown, no dropdown to choose a different one.
  expect(screen.getByText(/d7e8f9a/)).toBeInTheDocument();
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
});

test("Preview rollback button is disabled until the service name is typed exactly", () => {
  renderDialog();

  const button = screen.getByRole("button", { name: /preview rollback/i });
  expect(button).toBeDisabled();

  const confirm = screen.getByLabelText(/to confirm/i);
  fireEvent.change(confirm, { target: { value: "wfm-serv" } });
  expect(button).toBeDisabled();

  fireEvent.change(confirm, { target: { value: "wfm-service" } });
  expect(button).toBeEnabled();
});

test("clicking preview calls the rollback endpoint with the target sha and shows the inert result", async () => {
  const fetchSpy = vi.spyOn(global, "fetch").mockResolvedValue({
    ok: true,
    json: async () => ({
      service: "wfm-service",
      target_sha: "d7e8f9a0b1",
      executed: false,
      message:
        "Preview only — rollback execution is not implemented. No production change was made.",
    }),
  } as Response);

  renderDialog();

  fireEvent.change(screen.getByLabelText(/to confirm/i), {
    target: { value: "wfm-service" },
  });
  fireEvent.click(screen.getByRole("button", { name: /preview rollback/i }));

  await waitFor(() =>
    expect(screen.getByTestId("rollback-result")).toBeInTheDocument(),
  );

  expect(fetchSpy).toHaveBeenCalledTimes(1);
  const [url, init] = fetchSpy.mock.calls[0];
  expect(String(url)).toContain("/api/services/wfm-service/rollback");
  expect(String((init as RequestInit).body)).toContain("d7e8f9a0b1");

  expect(
    screen.getByText("Preview only — no production change was made."),
  ).toBeInTheDocument();
});

test("renders a PR link to the derived pull-request url", () => {
  renderDialog();
  const link = screen.getByRole("link", { name: /PR #7412/i });
  expect(link).toHaveAttribute(
    "href",
    "https://github.com/acme/platform/pull/7412",
  );
});

test("renders no PR link when the target has no pr_url", () => {
  renderDialog({ target: { ...target, pr_url: null } });
  expect(screen.queryByRole("link", { name: /PR #/i })).not.toBeInTheDocument();
});

test("confirm stays disabled when there is no target", () => {
  renderDialog({ target: null });
  fireEvent.change(screen.getByLabelText(/to confirm/i), {
    target: { value: "wfm-service" },
  });
  expect(
    screen.getByRole("button", { name: /preview rollback/i }),
  ).toBeDisabled();
});

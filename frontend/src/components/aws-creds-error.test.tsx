import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { AwsCredsError } from "@/components/aws-creds-error";

test("explains the re-assume + restart recovery and shows the backend command", () => {
  render(<AwsCredsError />);
  expect(
    screen.getByText(/AWS credentials missing or expired/i),
  ).toBeInTheDocument();
  expect(screen.getByText(/uvicorn maki\.api:app --port 8787/)).toBeInTheDocument();
  // It's announced as an alert for assistive tech.
  expect(screen.getByRole("alert")).toBeInTheDocument();
});

test("fires onRetry when the retry button is clicked", () => {
  const onRetry = vi.fn();
  render(<AwsCredsError onRetry={onRetry} />);
  fireEvent.click(screen.getByRole("button", { name: /retry/i }));
  expect(onRetry).toHaveBeenCalledOnce();
});

test("omits the retry button when no handler is given", () => {
  render(<AwsCredsError />);
  expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
});

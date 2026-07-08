// frontend/src/components/auth-gate.test.tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { AuthGate } from "@/components/auth-gate";
import { clearAuthToken, setAuthToken } from "@/lib/auth-token";

// Drive the gate's view of config without standing up the real provider/network.
vi.mock("@/components/config-provider", async (orig) => {
  const actual = await orig<typeof import("@/components/config-provider")>();
  return { ...actual, useConfig: () => mockConfig };
});
let mockConfig: { auth_required: boolean } = { auth_required: false };

afterEach(() => {
  clearAuthToken();
  mockConfig = { auth_required: false };
});

test("renders children when auth is not required", () => {
  mockConfig = { auth_required: false };
  render(
    <AuthGate>
      <div>dashboard</div>
    </AuthGate>,
  );
  expect(screen.getByText("dashboard")).toBeInTheDocument();
});

test("renders the login form when auth required and no token", () => {
  mockConfig = { auth_required: true };
  render(
    <AuthGate>
      <div>dashboard</div>
    </AuthGate>,
  );
  expect(screen.queryByText("dashboard")).not.toBeInTheDocument();
  expect(screen.getByLabelText(/token/i)).toBeInTheDocument();
});

test("submitting a token reveals the dashboard", () => {
  mockConfig = { auth_required: true };
  render(
    <AuthGate>
      <div>dashboard</div>
    </AuthGate>,
  );
  fireEvent.change(screen.getByLabelText(/token/i), { target: { value: "sekret" } });
  fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
  expect(screen.getByText("dashboard")).toBeInTheDocument();
});

test("re-gates on maki:unauthorized", () => {
  mockConfig = { auth_required: true };
  setAuthToken("good");
  render(
    <AuthGate>
      <div>dashboard</div>
    </AuthGate>,
  );
  expect(screen.getByText("dashboard")).toBeInTheDocument();
  fireEvent(window, new CustomEvent("maki:unauthorized"));
  expect(screen.queryByText("dashboard")).not.toBeInTheDocument();
});

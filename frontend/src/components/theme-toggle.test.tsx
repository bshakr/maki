import { fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { renderWithProviders } from "@/test-utils";
import { ThemeProvider } from "@/components/theme-provider";
import { ThemeToggle } from "@/components/theme-toggle";

beforeEach(() => {
  localStorage.clear();
  document.documentElement.className = "";
  // jsdom has no matchMedia; the provider calls it for "system".
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

test("a single click cycles the theme and applies .dark to <html>", () => {
  renderWithProviders(
    <ThemeProvider defaultTheme="light" storageKey="app-ui-theme">
      <ThemeToggle />
    </ThemeProvider>,
  );

  // light → dark: one plain-button click, no menu to open.
  fireEvent.click(screen.getByRole("button"));
  expect(document.documentElement.classList.contains("dark")).toBe(true);
  expect(localStorage.getItem("app-ui-theme")).toBe("dark");

  // dark → system (OS = light here) drops the class.
  fireEvent.click(screen.getByRole("button"));
  expect(localStorage.getItem("app-ui-theme")).toBe("system");
  expect(document.documentElement.classList.contains("dark")).toBe(false);
});

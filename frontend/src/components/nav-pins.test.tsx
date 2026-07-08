import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test } from "vitest";

import { NavPins } from "./nav-pins";
import { SidebarProvider } from "@/components/ui/sidebar";
import { getPins, pin, unpin } from "@/lib/pins";

function renderNav() {
  return render(
    <MemoryRouter>
      <SidebarProvider>
        <NavPins />
      </SidebarProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  localStorage.clear();
  for (const name of [...getPins()]) unpin(name);
});

afterEach(() => {
  for (const name of [...getPins()]) unpin(name);
  localStorage.clear();
});

test("renders nothing when there are no pins", () => {
  renderNav();
  expect(screen.queryByText("Pins")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("navigation", { name: /pinned services/i }),
  ).not.toBeInTheDocument();
});

test("renders pinned services as links to their detail pages", () => {
  pin("inventory");
  pin("workforce");
  renderNav();

  expect(screen.getByText("Pins")).toBeInTheDocument();

  const inventory = screen.getByRole("link", { name: /inventory/i });
  expect(inventory).toHaveAttribute("href", "/services/inventory");

  const workforce = screen.getByRole("link", { name: /workforce/i });
  expect(workforce).toHaveAttribute("href", "/services/workforce");
});

test("unpin action removes a pinned service", () => {
  pin("inventory");
  renderNav();

  expect(screen.getByRole("link", { name: /inventory/i })).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /unpin inventory/i }));

  expect(getPins()).toEqual([]);
  expect(
    screen.queryByRole("link", { name: /inventory/i }),
  ).not.toBeInTheDocument();
});

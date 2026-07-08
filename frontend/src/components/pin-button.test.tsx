import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test } from "vitest";

import { PinButton } from "./pin-button";
import { getPins, unpin } from "@/lib/pins";

beforeEach(() => {
  localStorage.clear();
  for (const name of [...getPins()]) unpin(name);
});

afterEach(() => {
  for (const name of [...getPins()]) unpin(name);
  localStorage.clear();
});

test("toggles pinned state and reflects aria-pressed", () => {
  render(<PinButton name="inventory" />);

  const btn = screen.getByRole("button", { name: /pin inventory/i });
  expect(btn).toHaveAttribute("aria-pressed", "false");

  fireEvent.click(btn);
  expect(getPins()).toEqual(["inventory"]);

  const unpinBtn = screen.getByRole("button", { name: /unpin inventory/i });
  expect(unpinBtn).toHaveAttribute("aria-pressed", "true");

  fireEvent.click(unpinBtn);
  expect(getPins()).toEqual([]);
});

test("stops click propagation when nested in a clickable parent", () => {
  let parentClicked = false;
  render(
    <div onClick={() => (parentClicked = true)}>
      <PinButton name="svc" />
    </div>,
  );

  fireEvent.click(screen.getByRole("button", { name: /pin svc/i }));
  expect(parentClicked).toBe(false);
  expect(getPins()).toEqual(["svc"]);
});

test("does not stop propagation when stopPropagation is false", () => {
  let parentClicked = false;
  render(
    <div onClick={() => (parentClicked = true)}>
      <PinButton name="svc" stopPropagation={false} />
    </div>,
  );

  fireEvent.click(screen.getByRole("button", { name: /pin svc/i }));
  expect(parentClicked).toBe(true);
});

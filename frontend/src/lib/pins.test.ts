import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test } from "vitest";

import {
  PINS_STORAGE_KEY,
  getPins,
  isPinned,
  pin,
  toggle,
  unpin,
  usePins,
} from "./pins";

// The store reads localStorage on module load, so each test resets to a known
// empty state by clearing storage and unpinning anything left behind.
beforeEach(() => {
  localStorage.clear();
  for (const name of [...getPins()]) unpin(name);
});

afterEach(() => {
  for (const name of [...getPins()]) unpin(name);
  localStorage.clear();
});

describe("pins store", () => {
  test("pin adds a name and persists to localStorage", () => {
    pin("inventory");
    expect(getPins()).toEqual(["inventory"]);
    expect(isPinned("inventory")).toBe(true);
    expect(JSON.parse(localStorage.getItem(PINS_STORAGE_KEY)!)).toEqual([
      "inventory",
    ]);
  });

  test("pin is idempotent — no duplicates", () => {
    pin("workforce");
    pin("workforce");
    expect(getPins()).toEqual(["workforce"]);
  });

  test("unpin removes a name and persists", () => {
    pin("a");
    pin("b");
    unpin("a");
    expect(getPins()).toEqual(["b"]);
    expect(JSON.parse(localStorage.getItem(PINS_STORAGE_KEY)!)).toEqual(["b"]);
  });

  test("toggle flips pinned state", () => {
    toggle("svc");
    expect(isPinned("svc")).toBe(true);
    toggle("svc");
    expect(isPinned("svc")).toBe(false);
  });
});

describe("usePins hook", () => {
  test("exposes pins + helpers and re-renders on change", () => {
    const { result } = renderHook(() => usePins());
    expect(result.current.pins).toEqual([]);

    act(() => result.current.toggle("forecasting"));
    expect(result.current.pins).toEqual(["forecasting"]);
    expect(result.current.isPinned("forecasting")).toBe(true);

    act(() => result.current.unpin("forecasting"));
    expect(result.current.pins).toEqual([]);
  });
});

describe("parse guard", () => {
  // We can't easily re-import the module per-test (the snapshot is module-level),
  // but the guard logic in readFromStorage is what matters. Exercise it through
  // a fresh storage event: a corrupt value must resolve to [].
  test("corrupt JSON in storage resolves to no pins via storage event", () => {
    localStorage.setItem(PINS_STORAGE_KEY, "{not json");
    act(() => {
      window.dispatchEvent(
        new StorageEvent("storage", { key: PINS_STORAGE_KEY }),
      );
    });
    expect(getPins()).toEqual([]);
  });

  test("non-array JSON resolves to no pins", () => {
    localStorage.setItem(PINS_STORAGE_KEY, JSON.stringify({ foo: 1 }));
    act(() => {
      window.dispatchEvent(
        new StorageEvent("storage", { key: PINS_STORAGE_KEY }),
      );
    });
    expect(getPins()).toEqual([]);
  });

  test("filters non-string + duplicate entries on read", () => {
    localStorage.setItem(
      PINS_STORAGE_KEY,
      JSON.stringify(["a", 3, "a", "", "b"]),
    );
    act(() => {
      window.dispatchEvent(
        new StorageEvent("storage", { key: PINS_STORAGE_KEY }),
      );
    });
    expect(getPins()).toEqual(["a", "b"]);
  });
});

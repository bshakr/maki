import { afterEach, expect, test } from "vitest";

import { clearAuthToken, getAuthToken, setAuthToken } from "@/lib/auth-token";

afterEach(() => clearAuthToken());

test("returns null when unset", () => {
  expect(getAuthToken()).toBeNull();
});

test("round-trips through localStorage", () => {
  setAuthToken("sekret");
  expect(getAuthToken()).toBe("sekret");
});

test("clear removes it", () => {
  setAuthToken("sekret");
  clearAuthToken();
  expect(getAuthToken()).toBeNull();
});

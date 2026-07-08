import { afterEach, beforeEach, expect, test, vi } from "vitest";

import {
  AwsCredentialsError,
  apiFetch,
  fetchDeployCount,
  fetchIdentity,
  fetchServiceEnv,
  fetchServices,
  isAwsCredentialsError,
} from "@/api";
import { clearAuthToken, setAuthToken } from "@/lib/auth-token";

afterEach(() => vi.restoreAllMocks());

function mockFetch(resp: Partial<Response> & { status: number; ok: boolean }) {
  vi.spyOn(global, "fetch").mockResolvedValue(resp as Response);
}

test("fetchIdentity returns the parsed identity on 200", async () => {
  mockFetch({
    ok: true,
    status: 200,
    json: async () => ({
      account: "123456789012",
      arn: "arn:aws:sts::123456789012:assumed-role/AdminRole/bob.smith",
      user_id: "X",
      name: "bob.smith",
      region: "eu-west-1",
    }),
  });
  const id = await fetchIdentity();
  expect(id.name).toBe("bob.smith");
  expect(id.account).toBe("123456789012");
});

test("a typed 503 raises AwsCredentialsError, detectable via isAwsCredentialsError", async () => {
  mockFetch({
    ok: false,
    status: 503,
    json: async () => ({
      error: "aws_credentials_unavailable",
      detail: "creds expired",
    }),
  });
  const err = await fetchIdentity().catch((e) => e);
  expect(err).toBeInstanceOf(AwsCredentialsError);
  expect(isAwsCredentialsError(err)).toBe(true);
});

test("fetchServices also surfaces the creds error", async () => {
  mockFetch({
    ok: false,
    status: 503,
    json: async () => ({ error: "aws_credentials_unavailable", detail: "x" }),
  });
  await expect(fetchServices()).rejects.toBeInstanceOf(AwsCredentialsError);
});

test("fetchServiceEnv also surfaces the creds error", async () => {
  mockFetch({
    ok: false,
    status: 503,
    json: async () => ({ error: "aws_credentials_unavailable", detail: "x" }),
  });
  await expect(fetchServiceEnv("workforce")).rejects.toBeInstanceOf(AwsCredentialsError);
});

test("a non-typed 503 stays a generic Error", async () => {
  mockFetch({ ok: false, status: 503, json: async () => ({ error: "something_else" }) });
  const err = await fetchIdentity().catch((e) => e);
  expect(err).toBeInstanceOf(Error);
  expect(isAwsCredentialsError(err)).toBe(false);
});

test("a 500 is a generic Error, not a creds error", async () => {
  mockFetch({ ok: false, status: 500, json: async () => ({}) });
  const err = await fetchServices().catch((e) => e);
  expect(isAwsCredentialsError(err)).toBe(false);
});

test("fetchDeployCount hits the deploy-count endpoint and returns the parsed body", async () => {
  const spy = vi.spyOn(global, "fetch").mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ count: 3, since: "2026-07-08T00:00:00Z", generated_at: "2026-07-08T12:00:00Z" }),
  } as Response);
  const result = await fetchDeployCount("2026-07-08T00:00:00Z");
  expect(spy.mock.calls[0][0]).toBe(
    "/api/activity/deploy-count?since=2026-07-08T00%3A00%3A00Z",
  );
  expect(result.count).toBe(3);
});

// apiFetch bearer-token tests
beforeEach(() => clearAuthToken());

test("attaches the Bearer header when a token is set", async () => {
  setAuthToken("sekret");
  const spy = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(new Response("{}", { status: 200 }));
  await apiFetch("/api/services");
  const init = spy.mock.calls[0][1] as RequestInit;
  expect(new Headers(init.headers).get("Authorization")).toBe("Bearer sekret");
});

test("sends no Authorization header when no token", async () => {
  const spy = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(new Response("{}", { status: 200 }));
  await apiFetch("/api/services");
  const init = spy.mock.calls[0][1] as RequestInit;
  expect(new Headers(init.headers).get("Authorization")).toBeNull();
});

test("clears token and dispatches maki:unauthorized on 401", async () => {
  setAuthToken("stale");
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("", { status: 401 }));
  const onUnauth = vi.fn();
  window.addEventListener("maki:unauthorized", onUnauth);
  await apiFetch("/api/services");
  window.removeEventListener("maki:unauthorized", onUnauth);
  expect(onUnauth).toHaveBeenCalled();
});

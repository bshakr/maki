import { screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { fetchAppConfig, type AppConfigResponse } from "@/api";
import { renderWithProviders } from "@/test-utils";

import { ConfigProvider, DEFAULT_APP_CONFIG, useConfig } from "./config-provider";

vi.mock("@/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api")>();
  return { ...actual, fetchAppConfig: vi.fn() };
});

const mockFetchAppConfig = vi.mocked(fetchAppConfig);

function Probe() {
  const cfg = useConfig();
  return (
    <div>
      name:{cfg.app_name} env:{cfg.env_label}
    </div>
  );
}

afterEach(() => vi.restoreAllMocks());

test("provides the fetched config to consumers", async () => {
  const config: AppConfigResponse = {
    ...DEFAULT_APP_CONFIG,
    app_name: "Acme Deploys",
    env_label: "prod",
  };
  mockFetchAppConfig.mockResolvedValue(config);

  renderWithProviders(
    <ConfigProvider>
      <Probe />
    </ConfigProvider>,
  );

  await waitFor(() =>
    expect(screen.getByText(/name:Acme Deploys/)).toBeInTheDocument(),
  );
  expect(screen.getByText(/env:prod/)).toBeInTheDocument();
});

test("falls back to neutral defaults before the fetch resolves", () => {
  // A pending fetch (never resolves) → consumers immediately see DEFAULT_APP_CONFIG, no crash.
  mockFetchAppConfig.mockReturnValue(new Promise<never>(() => {}));

  renderWithProviders(
    <ConfigProvider>
      <Probe />
    </ConfigProvider>,
  );

  expect(screen.getByText(/name:Deploy Dashboard/)).toBeInTheDocument();
});

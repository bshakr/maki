import { createContext, useContext, useEffect, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";

import { fetchAppConfig, type AppConfigResponse } from "@/api";
import { themeOverrideCss } from "@/lib/theme-overrides";

const THEME_STYLE_ID = "app-theme-overrides";

// Neutral fallback shown before the fetch resolves (or if it fails) so the first render never
// crashes. Defined here (not in @/api) so the context default survives tests that fully mock @/api.
export const DEFAULT_APP_CONFIG: AppConfigResponse = {
  app_name: "Deploy Dashboard",
  theme: null,
  env_label: "production",
  aws_region: "",
  log_group_template: "/ecs/{service}-production",
  amplify_enabled: false,
  grouping_rules: [],
  deploy_timeline_enabled: true,
  auth_required: false,
  watches_enabled: true,
};

// The ingested config is fetched once at boot and is static for the process, so we never refetch.
const ConfigContext = createContext<AppConfigResponse>(DEFAULT_APP_CONFIG);

export function ConfigProvider({ children }: { children: ReactNode }) {
  const { data } = useQuery({
    queryKey: ["app-config"],
    queryFn: fetchAppConfig,
    staleTime: Infinity,
    refetchInterval: false,
    refetchOnWindowFocus: false,
    retry: 1,
  });
  // Brand the document title from config once it resolves.
  useEffect(() => {
    if (data?.app_name) document.title = data.app_name;
  }, [data?.app_name]);

  // Inject the config-driven theme overrides as a <style> after index.css, so listed shadcn tokens
  // win over the vanilla defaults. No theme → remove the element (back to vanilla).
  useEffect(() => {
    const css = themeOverrideCss(data?.theme ?? null);
    let el = document.getElementById(THEME_STYLE_ID) as HTMLStyleElement | null;
    if (!css) {
      el?.remove();
      return;
    }
    if (!el) {
      el = document.createElement("style");
      el.id = THEME_STYLE_ID;
      document.head.appendChild(el);
    }
    el.textContent = css;
  }, [data?.theme]);
  return (
    <ConfigContext.Provider value={data ?? DEFAULT_APP_CONFIG}>
      {children}
    </ConfigContext.Provider>
  );
}

export function useConfig(): AppConfigResponse {
  return useContext(ConfigContext);
}

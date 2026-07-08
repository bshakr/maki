import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Route, Routes } from "react-router-dom";

import { AuthGate } from "@/components/auth-gate";
import { ConfigProvider } from "@/components/config-provider";
import { Layout } from "@/components/layout";
import { ActivityPage } from "@/pages/ActivityPage";
import { MetricsPage } from "@/pages/MetricsPage";
import { ServiceDetailPage } from "@/pages/ServiceDetailPage";
import { ServicesPage } from "@/pages/ServicesPage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      refetchInterval: false,
      refetchOnWindowFocus: true,
      retry: 1,
    },
  },
});

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ConfigProvider>
        <AuthGate>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<ServicesPage />} />
            <Route path="services/:name" element={<ServiceDetailPage />} />
            <Route
              path="services/:name/deploys/:sha"
              element={<ServiceDetailPage />}
            />
            <Route
              path="services/:name/tasks"
              element={<ServiceDetailPage />}
            />
            <Route
              path="services/:name/metrics"
              element={<ServiceDetailPage />}
            />
            <Route path="services/:name/env" element={<ServiceDetailPage />} />
            <Route path="activity" element={<ActivityPage />} />
            <Route path="metrics" element={<MetricsPage />} />
          </Route>
        </Routes>
        </AuthGate>
      </ConfigProvider>
    </QueryClientProvider>
  );
}

import path from "path";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  build: { outDir: "dist" },
  server: { proxy: { "/api": "http://localhost:8787" } },
  test: { globals: true, environment: "jsdom", setupFiles: ["./src/test-setup.ts"] },
});

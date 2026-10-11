// The dashboard's pages: built into dist/, which the dashboard API serves beside /api/v1.
// `npm run dev` serves them with hot reloading and hands /api and /setup to an API running
// locally on its default port.
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { svelteTesting } from "@testing-library/svelte/vite";
import { defineConfig } from "vitest/config";

const api = "http://127.0.0.1:2553";

export default defineConfig({
  // svelteTesting resolves Svelte's browser build under Vitest and cleans up after each test.
  plugins: [svelte(), svelteTesting()],
  server: {
    proxy: { "/api": api, "/setup": api, "/healthz": api },
  },
  build: { target: "es2022" },
  test: {
    environment: "jsdom",
    setupFiles: ["src/test-setup.ts"],
    include: ["src/**/*.test.ts"],
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,svelte}"],
      exclude: ["src/**/*.test.ts", "src/test-setup.ts", "src/main.ts", "src/testing.ts"],
      // json-summary and json are the istanbul files coverage.toml's shared tooling reads;
      // lcov is what Codecov takes.
      reporter: ["text", "json-summary", "json", "lcov", ["html", { subdir: "html" }]],
      reportsDirectory: "coverage",
    },
  },
});

// The dashboard's pages: built into dist/, which the dashboard API serves beside /api/v1.
// The dev server (`make dashboard-dev`) serves them with hot reloading and hands /api and /setup
// to an API running locally on its default port.
import { paraglideVitePlugin } from "@inlang/paraglide-js";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import legacy from "@vitejs/plugin-legacy";
import { legacyCssPlugin } from "./build/legacy-css.ts";
import { paraglideOptions } from "./build/paraglide.ts";
import { svelteTesting } from "@testing-library/svelte/vite";
import { test } from "@jmerhar/frontend-config/vitest";
import { defineConfig } from "vitest/config";

const api = "http://127.0.0.1:2553";

export default defineConfig({
  // svelteTesting resolves Svelte's browser build under Vitest and cleans up after each test.
  // legacy adds a second build, compiled down and polyfilled, that browsers without ES modules
  // load instead (<script nomodule>): Chrome 59 on an Android 4.4 tablet left on a wall. It sets
  // the modern build's target too: the browsers of es2022, and Safari 16 as well, because iPadOS 16
  // is still on tablets that cannot update and es2022 alone would leave in syntax it lacks, such
  // as class static blocks.
  // legacyCssPlugin gives the one stylesheet both builds share the fallbacks those browsers need.
  // paraglideVitePlugin compiles messages/ into src/paraglide before each build and test run.
  plugins: [
    paraglideVitePlugin(paraglideOptions),
    svelte(),
    svelteTesting(),
    legacy({
      targets: ["chrome >= 59"],
      modernTargets: ["chrome >= 94", "edge >= 94", "firefox >= 93", "safari >= 16", "ios_saf >= 16"],
    }),
    legacyCssPlugin(),
  ],
  server: {
    proxy: { "/api": api, "/setup": api, "/healthz": api },
  },
  // The licences of everything bundled into the page, which theirs ask to travel with it, at
  // /licenses.md beside it. The shared Vite preset is not used: plugin-legacy sets the build's
  // target from modernTargets, older browsers than the preset's, and overrides any other.
  build: { license: { fileName: "licenses.md" } },
  // The shared Vitest preset: jsdom, and v8 coverage in coverage/ for the shared gate and Codecov.
  test: {
    ...test({
      include: ["src/**/*.test.ts", "build/**/*.test.ts", "legacy-browser/**/*.test.mjs"],
      setupFiles: ["src/test-setup.ts"],
      coverage: {
        include: ["src/**/*.{ts,svelte}", "build/**/*.ts"],
        exclude: [
          "build/compile-messages.ts",
          "src/test-setup.ts",
          "src/main.ts",
          "src/testing.ts",
          "src/paraglide/**",
        ],
      },
    }),
    // Vitest empties every stylesheet it imports, ?raw included; theme.test.ts reads this one.
    css: { include: [/app\.css/] },
  },
});

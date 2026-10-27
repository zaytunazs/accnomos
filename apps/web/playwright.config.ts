import { defineConfig, devices } from "@playwright/test";
import { OUT_DIR, RUNTIME_PORT, RUNTIME_URL, WEB_URL } from "./e2e/env.mjs";

/**
 * End-to-end tests: the test-mode static export (`pnpm run e2e:build` → out-e2e/) against the runtime in test
 * mode (ACCNOMOS_TEST_MODE=1: fake OneDrive/Outlook/calendar, stub AI answering from evals/gold). Both servers
 * start here; nothing leaves 127.0.0.1 (e2e/fixtures.ts fails a test that tries).
 * Python: E2E_PYTHON (default `python3`) must have the runtime installed, e.g. `uv sync --all-packages`.
 */
const python = process.env.E2E_PYTHON ?? "python3";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1, // one shared fake OneDrive in the runtime; every test resets it
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL: WEB_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    locale: "en-GB",
    timezoneId: "Europe/London",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] }, testIgnore: /(phone|a11y)\.spec\.ts/ },
    { name: "phone", use: { ...devices["Pixel 7"] }, testMatch: /(phone|a11y)\.spec\.ts/ },
  ],
  webServer: [
    {
      command: `${python} -m uvicorn app.main:app --app-dir ../../services/runtime --host 127.0.0.1 --port ${RUNTIME_PORT} --no-access-log`,
      url: `${RUNTIME_URL}/health`,
      // RATE_LIMIT_PER_MIN=0: one browser on 127.0.0.1 makes well over 60 calls a minute across the suite.
      env: { ACCNOMOS_TEST_MODE: "1", PORT: String(RUNTIME_PORT), CORS_ORIGINS: WEB_URL, RATE_LIMIT_PER_MIN: "0" },
      reuseExistingServer: !process.env.CI,
      stdout: "pipe",
      timeout: 60_000,
    },
    {
      command: "node e2e/serve.mjs",
      url: WEB_URL,
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
  ],
  outputDir: "test-results",
  metadata: { export: OUT_DIR },
});

import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "tests/e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  retries: 1,
  workers: 2,
  reporter: [
    ["html", { outputFolder: "coverage/e2e", open: "never" }],
    ["list"],
  ],
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://127.0.0.1:8000",
    headless: true,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { browserName: "chromium" },
    },
  ],
  webServer: {
    command: "python run.py",
    port: 8000,
    timeout: 30_000,
    reuseExistingServer: true,
  },
});

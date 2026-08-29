import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

const stateRoot = path.resolve("..", ".e2e-real");

export default defineConfig({
  testDir: "./e2e-real",
  outputDir: "./test-results-real",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI
    ? [["line"], ["html", { open: "never", outputFolder: "playwright-report-real" }]]
    : "list",
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    { name: "chromium-real-stack", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: [
    {
      command: `python3.14 ../backend/tests/e2e_real_server.py --root ${JSON.stringify(stateRoot)} --port 5000`,
      url: "http://127.0.0.1:5000/api/__e2e/meta",
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 4173",
      url: "http://127.0.0.1:4173",
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});

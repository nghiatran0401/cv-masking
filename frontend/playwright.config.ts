import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "off",
    video: "off",
    screenshot: "off",
  },
  webServer: [
    {
      command: "cd ../backend && uv run --locked python -m cv_masking",
      url: "http://127.0.0.1:8765/api/health",
      reuseExistingServer: true,
      timeout: 120_000,
    },
    {
      command: "npm run dev",
      url: "http://127.0.0.1:5173",
      reuseExistingServer: true,
      timeout: 60_000,
    },
  ],
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});

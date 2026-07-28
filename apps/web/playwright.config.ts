import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

const repositoryRoot = path.resolve(__dirname, "../..");
const runDatabase = path.join(
  repositoryRoot,
  "apps",
  "api",
  ".playwright-data",
  `diagnostic-${Date.now()}.db`,
);
const externalServers = process.env.PLAYWRIGHT_EXTERNAL_SERVERS === "1";
const completionFile = process.env.PLAYWRIGHT_COMPLETION_FILE;

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 2 : 0,
  reporter: completionFile
    ? [
        [process.env.CI ? "github" : "list"],
        [
          path.join(__dirname, "e2e", "completion-reporter.ts"),
          { outputFile: completionFile },
        ],
      ]
    : process.env.CI
      ? "github"
      : "list",
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:3000",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "mobile-chromium",
      use: { ...devices["Pixel 7"] },
    },
  ],
  webServer: externalServers
    ? undefined
    : [
        {
          command:
            "uv run --project apps/api --locked uvicorn cloud_study_api.main:app --app-dir apps/api/src --host 127.0.0.1 --port 8000",
          cwd: repositoryRoot,
          env: {
            CLOUD_STUDY_DATABASE_PATH: runDatabase,
            UV_CACHE_DIR: path.join(repositoryRoot, ".uv-cache"),
          },
          port: 8000,
          reuseExistingServer: false,
          timeout: 120_000,
        },
        {
          command: "pnpm --filter @cloud-study/web dev --hostname 127.0.0.1",
          cwd: repositoryRoot,
          env: {
            NEXT_TELEMETRY_DISABLED: "1",
          },
          port: 3000,
          reuseExistingServer: false,
          timeout: 120_000,
        },
      ],
});

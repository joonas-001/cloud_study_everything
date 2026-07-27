import { spawn, spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const isWindows = process.platform === "win32";
const runDatabase = path.join(
  repositoryRoot,
  "apps",
  "api",
  ".playwright-data",
  `diagnostic-${Date.now()}.db`,
);
const completionFile = path.join(
  repositoryRoot,
  "apps",
  "api",
  ".playwright-data",
  `completion-${Date.now()}.json`,
);

function start(command, args, environment = {}) {
  return spawn(command, args, {
    cwd: repositoryRoot,
    detached: !isWindows,
    env: { ...process.env, ...environment },
    stdio: "inherit",
    shell: false,
  });
}

async function waitForUrl(url, child, timeoutMs = 120_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(`${url} server exited with code ${child.exitCode}`);
    }
    try {
      const response = await fetch(url);
      if (response.ok) {
        return;
      }
    } catch {
      // The service has not opened its socket yet.
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  throw new Error(`Timed out waiting for ${url}`);
}

function stop(child) {
  if (child.pid === undefined || child.exitCode !== null) {
    return;
  }
  if (isWindows) {
    child.kill("SIGKILL");
    spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], {
      stdio: "ignore",
      timeout: 3_000,
    });
    child.unref();
    return;
  }
  process.kill(-child.pid, "SIGTERM");
}

async function waitForCompletionFile(child, timeoutMs = 120_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (existsSync(completionFile)) {
      const result = JSON.parse(readFileSync(completionFile, "utf8"));
      return result.status === "passed" ? 0 : 1;
    }
    if (child.exitCode !== null) {
      return child.exitCode ?? 1;
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("Timed out waiting for the Playwright completion report");
}

const api = start(
  "uv",
  [
    "run",
    "--project",
    "apps/api",
    "--locked",
    "uvicorn",
    "cloud_study_api.main:app",
    "--app-dir",
    "apps/api/src",
    "--host",
    "127.0.0.1",
    "--port",
    "8000",
  ],
  {
    CLOUD_STUDY_DATABASE_PATH: runDatabase,
    UV_CACHE_DIR: path.join(repositoryRoot, ".uv-cache"),
  },
);
const web = start(
  process.execPath,
  [
    path.join(
      repositoryRoot,
      "apps",
      "web",
      "node_modules",
      "next",
      "dist",
      "bin",
      "next",
    ),
    "dev",
    "apps/web",
    "--hostname",
    "127.0.0.1",
  ],
  { NEXT_TELEMETRY_DISABLED: "1" },
);

let exitCode = 1;
try {
  await Promise.all([
    waitForUrl("http://127.0.0.1:8000/health", api),
    waitForUrl("http://127.0.0.1:3000/diagnostic", web),
  ]);
  const playwright = start(
    process.execPath,
    [
      path.join(
        repositoryRoot,
        "apps",
        "web",
        "node_modules",
        "@playwright",
        "test",
        "cli.js",
      ),
      "test",
      "--config",
      "apps/web/playwright.config.ts",
    ],
    {
      PLAYWRIGHT_COMPLETION_FILE: completionFile,
      PLAYWRIGHT_EXTERNAL_SERVERS: "1",
    },
  );
  try {
    exitCode = await waitForCompletionFile(playwright);
  } finally {
    stop(playwright);
  }
} finally {
  stop(web);
  stop(api);
}

process.exitCode = exitCode;

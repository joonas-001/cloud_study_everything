import { spawn, spawnSync } from "node:child_process";
import { existsSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import net from "node:net";
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
const webRoot = path.join(repositoryRoot, "apps", "web");
const e2eNextDistName = ".next-e2e";
const e2eNextDist = path.join(webRoot, e2eNextDistName);
const nextEnvPath = path.join(webRoot, "next-env.d.ts");
const nextEnvExisted = existsSync(nextEnvPath);
const nextEnvOriginal = nextEnvExisted ? readFileSync(nextEnvPath) : null;
const trackedChildren = new Set();

function start(command, args, environment = {}) {
  const child = spawn(command, args, {
    cwd: repositoryRoot,
    detached: !isWindows,
    env: { ...process.env, ...environment },
    stdio: "inherit",
    shell: false,
  });
  trackedChildren.add(child);
  return child;
}

function reservePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (typeof address === "string" || address === null) {
        server.close();
        reject(new Error("Could not reserve a local TCP port"));
        return;
      }
      server.close(() => resolve(address.port));
    });
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

function terminateWindowsProcessTree(processId) {
  const result = spawnSync("taskkill", ["/PID", String(processId), "/T", "/F"], {
    stdio: "ignore",
    timeout: 5_000,
    windowsHide: true,
  });
  if (result.status === 0) {
    return true;
  }
  try {
    process.kill(processId, "SIGKILL");
    return true;
  } catch (error) {
    return error instanceof Error && "code" in error && error.code === "ESRCH";
  }
}

function stop(child) {
  if (child.pid === undefined) {
    trackedChildren.delete(child);
    return;
  }
  if (isWindows) {
    const parentStopped = terminateWindowsProcessTree(child.pid);
    if (!parentStopped && child.exitCode === null) {
      child.kill("SIGKILL");
    }
    trackedChildren.delete(child);
    child.unref();
    return;
  }
  if (child.exitCode === null) {
    process.kill(-child.pid, "SIGTERM");
  }
  trackedChildren.delete(child);
}

function stopAll() {
  for (const child of [...trackedChildren]) {
    stop(child);
  }
}

function restoreNextEnv() {
  if (nextEnvOriginal !== null) {
    writeFileSync(nextEnvPath, nextEnvOriginal);
  } else if (!nextEnvExisted) {
    rmSync(nextEnvPath, { force: true });
  }
}

async function removeE2eNextDist() {
  const resolvedWebRoot = path.resolve(webRoot);
  const resolvedTarget = path.resolve(e2eNextDist);
  if (
    path.dirname(resolvedTarget) !== resolvedWebRoot ||
    path.basename(resolvedTarget) !== ".next-e2e"
  ) {
    throw new Error(`Refusing to remove unsafe E2E build directory: ${resolvedTarget}`);
  }
  for (let attempt = 0; attempt < 20; attempt += 1) {
    try {
      rmSync(resolvedTarget, { recursive: true, force: true });
      return;
    } catch (error) {
      if (
        !(error instanceof Error) ||
        !("code" in error) ||
        !["EBUSY", "EPERM", "ENOTEMPTY"].includes(String(error.code)) ||
        attempt === 19
      ) {
        throw error;
      }
      await new Promise((resolve) => setTimeout(resolve, 200));
    }
  }
}

function isPortListening(port) {
  return new Promise((resolve) => {
    const socket = net.createConnection({ host: "127.0.0.1", port });
    socket.once("connect", () => {
      socket.destroy();
      resolve(true);
    });
    socket.once("error", () => {
      socket.destroy();
      resolve(false);
    });
    socket.setTimeout(500, () => {
      socket.destroy();
      resolve(false);
    });
  });
}

async function waitForPortRelease(port, timeoutMs = 5_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (!(await isPortListening(port))) {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Timed out waiting for 127.0.0.1:${port} to close`);
}

process.once("SIGINT", () => {
  stopAll();
  restoreNextEnv();
  process.exit(130);
});
process.once("SIGTERM", () => {
  stopAll();
  restoreNextEnv();
  process.exit(143);
});
process.once("exit", () => {
  stopAll();
  restoreNextEnv();
});

async function waitForCompletionFile(child, timeoutMs = 600_000) {
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

const apiPort = await reservePort();
let webPort = await reservePort();
while (webPort === apiPort) {
  webPort = await reservePort();
}
const apiBaseUrl = `http://127.0.0.1:${apiPort}`;
const webBaseUrl = `http://127.0.0.1:${webPort}`;
const apiPython = path.join(
  repositoryRoot,
  "apps",
  "api",
  ".venv",
  isWindows ? "Scripts" : "bin",
  isWindows ? "python.exe" : "python",
);
if (!existsSync(apiPython)) {
  throw new Error(
    `Missing ${apiPython}; run the project bootstrap or locked dependency install first`,
  );
}

await removeE2eNextDist();

const api = start(
  apiPython,
  [
    "-m",
    "uvicorn",
    "e2e_app:app",
    "--app-dir",
    "apps/api/tests",
    "--host",
    "127.0.0.1",
    "--port",
    String(apiPort),
  ],
  {
    CLOUD_STUDY_DATABASE_PATH: runDatabase,
    PYTHONPATH: path.join(repositoryRoot, "apps", "api", "src"),
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
    "--port",
    String(webPort),
  ],
  {
    CLOUD_STUDY_E2E_NEXT_DIST_DIR: e2eNextDistName,
    CLOUD_STUDY_API_INTERNAL_URL: apiBaseUrl,
    NEXT_PUBLIC_API_BASE_URL: "/api",
    NEXT_TELEMETRY_DISABLED: "1",
  },
);

let exitCode = 1;
try {
  await Promise.all([
    waitForUrl(`${apiBaseUrl}/health`, api),
    waitForUrl(`${webBaseUrl}/diagnostic`, web),
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
      PLAYWRIGHT_BASE_URL: webBaseUrl,
      PLAYWRIGHT_API_BASE_URL: apiBaseUrl,
      PLAYWRIGHT_BROWSER_API_BASE_URL: `${webBaseUrl}/api`,
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
  await Promise.all([
    waitForPortRelease(webPort),
    waitForPortRelease(apiPort),
  ]);
  await removeE2eNextDist();
  restoreNextEnv();
}

process.exitCode = exitCode;

import { spawn, spawnSync } from "node:child_process";
import {
  closeSync,
  existsSync,
  mkdirSync,
  openSync,
  readFileSync,
  renameSync,
  unlinkSync,
  writeSync,
  writeFileSync,
} from "node:fs";
import http from "node:http";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const isWindows = process.platform === "win32";
const runtimeDirectory = path.join(repositoryRoot, ".tmp", "local-services");
const statePath = path.join(runtimeDirectory, "state.json");
const stateTemporaryPath = path.join(runtimeDirectory, "state.json.tmp");
const apiPidPath = path.join(runtimeDirectory, "api.pid");
const apiPort = 8000;
const webPort = 3000;
const readinessTimeoutMs = 45_000;

function requireNode24() {
  const major = Number.parseInt(process.versions.node.split(".", 1)[0], 10);
  if (major !== 24) {
    throw new Error(
      `Local services require Node.js 24, but this process is using ${process.version}`,
    );
  }
}

function normalizedEnvironment(overrides = {}) {
  const environment = {};
  let inheritedPath = "";
  for (const [key, value] of Object.entries(process.env)) {
    if (key.toLowerCase() === "path") {
      inheritedPath ||= value ?? "";
      continue;
    }
    if (value !== undefined) {
      environment[key] = value;
    }
  }
  const pathEntries = [path.dirname(process.execPath)];
  if (inheritedPath) {
    pathEntries.push(inheritedPath);
  }
  environment[isWindows ? "Path" : "PATH"] = pathEntries.join(path.delimiter);
  return { ...environment, ...overrides };
}

function readState() {
  if (!existsSync(statePath)) {
    return null;
  }
  return JSON.parse(readFileSync(statePath, "utf8"));
}

function writeState(state) {
  mkdirSync(runtimeDirectory, { recursive: true });
  writeFileSync(stateTemporaryPath, `${JSON.stringify(state, null, 2)}\n`, "utf8");
  renameSync(stateTemporaryPath, statePath);
}

function removeState() {
  if (existsSync(stateTemporaryPath)) {
    unlinkSync(stateTemporaryPath);
  }
  if (existsSync(statePath)) {
    unlinkSync(statePath);
  }
  if (existsSync(apiPidPath)) {
    unlinkSync(apiPidPath);
  }
}

function isProcessAlive(processId) {
  if (!Number.isInteger(processId) || processId <= 0) {
    return false;
  }
  try {
    process.kill(processId, 0);
    return true;
  } catch (error) {
    return !(error instanceof Error && "code" in error && error.code === "ESRCH");
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

async function probeUrl(url) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) {
        return;
      }
      settled = true;
      resolve(value);
    };
    const request = http.get(url, { agent: false }, (response) => {
      response.resume();
      response.once("end", () => {
        finish(
          response.statusCode !== undefined &&
            response.statusCode >= 200 &&
            response.statusCode < 300,
        );
      });
    });
    request.once("error", () => finish(false));
    request.setTimeout(1_500, () => {
      request.destroy();
      finish(false);
    });
  });
}

async function waitForUrl(url, processId, timeoutMs = readinessTimeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (!isProcessAlive(processId)) {
      throw new Error(`${url} process ${processId} exited before becoming ready`);
    }
    if (await probeUrl(url)) {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  throw new Error(`Timed out after ${timeoutMs}ms waiting for ${url}`);
}

function startDetached(command, args, environment, logPrefix) {
  mkdirSync(runtimeDirectory, { recursive: true });
  const stdoutPath = path.join(runtimeDirectory, `${logPrefix}.out.log`);
  const stderrPath = path.join(runtimeDirectory, `${logPrefix}.err.log`);
  const stdout = openSync(stdoutPath, "a");
  const stderr = openSync(stderrPath, "a");
  try {
    const child = spawn(command, args, {
      cwd: repositoryRoot,
      detached: true,
      env: normalizedEnvironment(environment),
      shell: false,
      stdio: ["ignore", stdout, stderr],
      windowsHide: true,
    });
    if (child.pid === undefined) {
      throw new Error(`Failed to start ${logPrefix}`);
    }
    child.unref();
    return {
      pid: child.pid,
      stdout_path: path.relative(repositoryRoot, stdoutPath),
      stderr_path: path.relative(repositoryRoot, stderrPath),
    };
  } finally {
    closeSync(stdout);
    closeSync(stderr);
  }
}

async function waitForPidFile(pidPath, launcherPid, timeoutMs = 5_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (existsSync(pidPath)) {
      const processId = Number.parseInt(readFileSync(pidPath, "utf8").trim(), 10);
      if (Number.isInteger(processId) && processId > 0 && isProcessAlive(processId)) {
        return processId;
      }
    }
    if (!isProcessAlive(launcherPid) && !existsSync(pidPath)) {
      throw new Error(`Launcher process ${launcherPid} exited before writing ${pidPath}`);
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error(`Timed out waiting for the service PID file ${pidPath}`);
}

function terminateProcessTree(processId) {
  if (!isProcessAlive(processId)) {
    return;
  }
  if (isWindows) {
    const result = spawnSync("taskkill", ["/PID", String(processId), "/T", "/F"], {
      env: normalizedEnvironment(),
      stdio: "ignore",
      timeout: 5_000,
      windowsHide: true,
    });
    if (result.status === 0) {
      return;
    }
  }
  try {
    process.kill(processId, "SIGKILL");
  } catch (error) {
    if (!(error instanceof Error && "code" in error && error.code === "ESRCH")) {
      throw error;
    }
  }
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

async function statusPayload() {
  const state = readState();
  if (state === null) {
    return {
      status: "stopped",
      api: { port: apiPort, listening: await isPortListening(apiPort) },
      web: { port: webPort, listening: await isPortListening(webPort) },
    };
  }
  const [apiListening, webListening, apiHealthy, webHealthy] = await Promise.all([
    isPortListening(apiPort),
    isPortListening(webPort),
    probeUrl(`http://127.0.0.1:${apiPort}/health`),
    probeUrl(`http://127.0.0.1:${webPort}/settings`),
  ]);
  const apiAlive = isProcessAlive(state.api.pid);
  const webAlive = isProcessAlive(state.web.pid);
  return {
    status:
      apiAlive && webAlive && apiListening && webListening && apiHealthy && webHealthy
        ? "running"
        : "degraded",
    started_at: state.started_at,
    api: {
      ...state.api,
      alive: apiAlive,
      port: apiPort,
      listening: apiListening,
      healthy: apiHealthy,
    },
    web: {
      ...state.web,
      alive: webAlive,
      port: webPort,
      listening: webListening,
      healthy: webHealthy,
    },
  };
}

async function startServices() {
  const currentState = readState();
  if (currentState !== null) {
    const currentStatus = await statusPayload();
    if (currentStatus.status === "running") {
      throw new Error("Local services are already running");
    }
    if (isProcessAlive(currentState.api.pid) || isProcessAlive(currentState.web.pid)) {
      throw new Error(
        "Local service state is degraded; run local-services:stop before starting again",
      );
    }
    removeState();
  }
  const [apiOccupied, webOccupied] = await Promise.all([
    isPortListening(apiPort),
    isPortListening(webPort),
  ]);
  if (apiOccupied || webOccupied) {
    throw new Error(
      `Required port is already in use: ${apiOccupied ? apiPort : ""}${
        apiOccupied && webOccupied ? ", " : ""
      }${webOccupied ? webPort : ""}`,
    );
  }

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
      `Missing ${apiPython}; run the locked backend dependency installation first`,
    );
  }
  const nextCli = path.join(
    repositoryRoot,
    "apps",
    "web",
    "node_modules",
    "next",
    "dist",
    "bin",
    "next",
  );
  if (!existsSync(nextCli)) {
    throw new Error(
      `Missing ${nextCli}; run pnpm install --frozen-lockfile before starting services`,
    );
  }

  if (existsSync(apiPidPath)) {
    unlinkSync(apiPidPath);
  }
  const apiLauncher = startDetached(
    apiPython,
    ["tools/run_local_api.py"],
    {
      PYTHONPATH: path.join(repositoryRoot, "apps", "api", "src"),
      CLOUD_STUDY_LOCAL_API_PID_PATH: apiPidPath,
    },
    "api",
  );
  const api = {
    ...apiLauncher,
    launcher_pid: apiLauncher.pid,
    pid: await waitForPidFile(apiPidPath, apiLauncher.pid),
  };
  let web;
  try {
    web = startDetached(
      process.execPath,
      [nextCli, "dev", "apps/web", "--hostname", "127.0.0.1", "--port", String(webPort)],
      {
        NEXT_PUBLIC_API_BASE_URL: `http://127.0.0.1:${apiPort}`,
        NEXT_TELEMETRY_DISABLED: "1",
      },
      "web",
    );
  } catch (error) {
    terminateProcessTree(api.pid);
    throw error;
  }

  const state = {
    schema_version: 1,
    started_at: new Date().toISOString(),
    node_version: process.version,
    api,
    web,
  };
  writeState(state);
  try {
    await Promise.all([
      waitForUrl(`http://127.0.0.1:${apiPort}/health`, api.pid),
      waitForUrl(`http://127.0.0.1:${webPort}/settings`, web.pid),
    ]);
  } catch (error) {
    terminateProcessTree(web.pid);
    terminateProcessTree(api.pid);
    await Promise.allSettled([
      waitForPortRelease(webPort),
      waitForPortRelease(apiPort),
    ]);
    removeState();
    throw error;
  }
  return statusPayload();
}

async function stopServices() {
  const state = readState();
  if (state === null) {
    return statusPayload();
  }
  terminateProcessTree(state.web.pid);
  terminateProcessTree(state.api.pid);
  await Promise.all([waitForPortRelease(webPort), waitForPortRelease(apiPort)]);
  removeState();
  return statusPayload();
}

requireNode24();
const command = process.argv[2] ?? "status";
let result;
if (command === "start") {
  result = await startServices();
} else if (command === "stop") {
  result = await stopServices();
} else if (command === "status") {
  result = await statusPayload();
} else {
  throw new Error(`Unsupported command ${command}; use start, status, or stop`);
}
writeSync(1, `${JSON.stringify(result, null, 2)}\n`);
process.exitCode = command === "status" && result.status === "degraded" ? 1 : 0;

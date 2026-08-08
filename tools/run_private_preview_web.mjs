import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
if (path.resolve(process.cwd()) !== repositoryRoot) {
  throw new Error(`Private preview web must start from ${repositoryRoot}`);
}
if (Number.parseInt(process.versions.node.split(".", 1)[0], 10) !== 24) {
  throw new Error(`Private preview web requires Node.js 24, got ${process.version}`);
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
  throw new Error(`Missing locked Next.js runtime at ${nextCli}`);
}

const child = spawn(
  process.execPath,
  [nextCli, "start", "apps/web", "--hostname", "127.0.0.1", "--port", "3000"],
  {
    cwd: repositoryRoot,
    env: process.env,
    stdio: "inherit",
    windowsHide: true,
  },
);
for (const signal of ["SIGINT", "SIGTERM"]) {
  process.once(signal, () => child.kill(signal));
}
child.once("error", (error) => {
  throw error;
});
child.once("exit", (code, signal) => {
  if (signal !== null) {
    process.kill(process.pid, signal);
    return;
  }
  process.exitCode = code ?? 1;
});

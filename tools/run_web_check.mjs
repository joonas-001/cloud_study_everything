import { spawnSync } from "node:child_process";
import {
  existsSync,
  readFileSync,
  readdirSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const nextEnvironmentPath = path.join(repositoryRoot, "apps", "web", "next-env.d.ts");
const originalExists = existsSync(nextEnvironmentPath);
const originalBytes = originalExists ? readFileSync(nextEnvironmentPath) : null;
const pnpmCli = process.env.npm_execpath;

if (Number.parseInt(process.versions.node.split(".", 1)[0], 10) !== 24) {
  throw new Error(`Web checks require Node.js 24, got ${process.version}`);
}
if (!pnpmCli || !existsSync(pnpmCli)) {
  throw new Error("Web checks must be invoked through the locked pnpm package script");
}

function runPnpm(args) {
  const result = spawnSync(process.execPath, [pnpmCli, ...args], {
    cwd: repositoryRoot,
    env: { ...process.env, NEXT_TELEMETRY_DISABLED: "1" },
    stdio: "inherit",
    windowsHide: true,
  });
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    throw new Error(`pnpm ${args.join(" ")} failed with status ${result.status}`);
  }
}

function javascriptFiles(directory) {
  const files = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const entryPath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...javascriptFiles(entryPath));
    } else if (entry.isFile() && entry.name.endsWith(".js")) {
      files.push(entryPath);
    }
  }
  return files;
}

function assertProductionApiBoundary() {
  const chunksDirectory = path.join(
    repositoryRoot,
    "apps",
    "web",
    ".next",
    "static",
    "chunks",
  );
  if (!existsSync(chunksDirectory)) {
    throw new Error(`Missing production browser chunks at ${chunksDirectory}`);
  }

  let sameOriginApiFound = false;
  for (const filePath of javascriptFiles(chunksDirectory)) {
    const content = readFileSync(filePath, "utf8");
    if (
      content.includes("http://127.0.0.1:8000") ||
      content.includes("http://localhost:8000")
    ) {
      throw new Error(
        `Production browser chunk must not contain a loopback API origin: ${filePath}`,
      );
    }
    sameOriginApiFound ||= content.includes('"/api"');
  }
  if (!sameOriginApiFound) {
    throw new Error("Production browser chunks do not contain the same-origin /api base");
  }
}

try {
  for (const command of ["lint", "typecheck", "test", "build"]) {
    runPnpm(["--filter", "@cloud-study/web", command]);
  }
  assertProductionApiBoundary();
} finally {
  if (originalExists && originalBytes !== null) {
    writeFileSync(nextEnvironmentPath, originalBytes);
  } else if (existsSync(nextEnvironmentPath)) {
    unlinkSync(nextEnvironmentPath);
  }
}

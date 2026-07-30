import type { NextConfig } from "next";

const e2eDistDir = process.env.CLOUD_STUDY_E2E_NEXT_DIST_DIR;
if (e2eDistDir && e2eDistDir !== ".next-e2e") {
  throw new Error("CLOUD_STUDY_E2E_NEXT_DIST_DIR must be a safe local E2E directory name");
}

const nextConfig: NextConfig = {
  reactStrictMode: true,
  ...(e2eDistDir ? { distDir: e2eDistDir } : {}),
};

export default nextConfig;

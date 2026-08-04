import type { NextConfig } from "next";

const e2eDistDir = process.env.CLOUD_STUDY_E2E_NEXT_DIST_DIR;
if (e2eDistDir && e2eDistDir !== ".next-e2e") {
  throw new Error("CLOUD_STUDY_E2E_NEXT_DIST_DIR must be a safe local E2E directory name");
}

function internalApiOrigin(): string {
  const configured =
    process.env.CLOUD_STUDY_API_INTERNAL_URL ?? "http://127.0.0.1:8000";
  const parsed = new URL(configured);
  if (
    parsed.protocol !== "http:" ||
    !["127.0.0.1", "localhost"].includes(parsed.hostname) ||
    parsed.username ||
    parsed.password ||
    parsed.pathname !== "/" ||
    parsed.search ||
    parsed.hash
  ) {
    throw new Error(
      "CLOUD_STUDY_API_INTERNAL_URL must be one exact loopback HTTP origin",
    );
  }
  return parsed.origin;
}

const apiOrigin = internalApiOrigin();
const scriptPolicy =
  process.env.NODE_ENV === "development"
    ? "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
    : "script-src 'self' 'unsafe-inline'; ";
const connectPolicy =
  process.env.NODE_ENV === "development"
    ? "connect-src 'self' http://127.0.0.1:* http://localhost:*; "
    : "connect-src 'self'; ";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: "standalone",
  poweredByHeader: false,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          {
            key: "Content-Security-Policy",
            value:
              "default-src 'self'; base-uri 'self'; " +
              connectPolicy +
              "font-src 'self'; form-action 'self'; frame-ancestors 'none'; " +
              "img-src 'self' data:; object-src 'none'; " +
              scriptPolicy +
              "style-src 'self' 'unsafe-inline'",
          },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
          },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
        ],
      },
    ];
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiOrigin}/:path*`,
      },
    ];
  },
  ...(e2eDistDir ? { distDir: e2eDistDir } : {}),
};

export default nextConfig;

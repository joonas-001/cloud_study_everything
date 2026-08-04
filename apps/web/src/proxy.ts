import { type NextRequest, NextResponse } from "next/server";

type HeaderReader = Pick<Headers, "get">;

export interface PrivatePreviewAuthorization {
  allowed: boolean;
  status: 200 | 401 | 403 | 503;
  code: "ok" | "authentication_required" | "owner_identity_required" | "owner_login_missing";
}

export function privatePreviewAuthorization(
  headers: HeaderReader,
  deploymentMode = process.env.CLOUD_STUDY_DEPLOYMENT_MODE,
  ownerLogin = process.env.CLOUD_STUDY_OWNER_LOGIN,
): PrivatePreviewAuthorization {
  if (deploymentMode !== "private_preview") {
    return { allowed: true, status: 200, code: "ok" };
  }
  const expected = ownerLogin?.trim().toLowerCase() ?? "";
  if (!expected) {
    return { allowed: false, status: 503, code: "owner_login_missing" };
  }
  const actual = headers.get("Tailscale-User-Login")?.trim().toLowerCase() ?? "";
  if (!actual) {
    return { allowed: false, status: 401, code: "authentication_required" };
  }
  if (actual !== expected) {
    return { allowed: false, status: 403, code: "owner_identity_required" };
  }
  return { allowed: true, status: 200, code: "ok" };
}

export function proxy(request: NextRequest): NextResponse {
  const authorization = privatePreviewAuthorization(request.headers);
  if (authorization.allowed) {
    return NextResponse.next();
  }
  return NextResponse.json(
    {
      detail: {
        code: authorization.code,
        message: "当前私有预发布只允许项目所有者访问。",
      },
    },
    { status: authorization.status },
  );
}

export const config = {
  matcher: ["/((?!api/|_next/static|_next/image|favicon.ico).*)"],
};

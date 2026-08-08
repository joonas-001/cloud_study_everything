import { describe, expect, it } from "vitest";

import { privatePreviewAuthorization } from "./proxy";

function headers(login?: string): Headers {
  const value = new Headers();
  if (login !== undefined) {
    value.set("Tailscale-User-Login", login);
  }
  return value;
}

describe("privatePreviewAuthorization", () => {
  it("does not add authentication to local development", () => {
    expect(privatePreviewAuthorization(headers(), "local", undefined)).toEqual({
      allowed: true,
      status: 200,
      code: "ok",
    });
  });

  it("fails closed when the owner login is missing", () => {
    expect(privatePreviewAuthorization(headers(), "private_preview", "")).toEqual({
      allowed: false,
      status: 503,
      code: "owner_login_missing",
    });
  });

  it("requires the exact Tailscale owner identity", () => {
    expect(
      privatePreviewAuthorization(headers(), "private_preview", "owner@example.com"),
    ).toMatchObject({ allowed: false, status: 401, code: "authentication_required" });
    expect(
      privatePreviewAuthorization(
        headers("other@example.com"),
        "private_preview",
        "owner@example.com",
      ),
    ).toMatchObject({ allowed: false, status: 403, code: "owner_identity_required" });
    expect(
      privatePreviewAuthorization(
        headers("Owner@Example.com"),
        "private_preview",
        "owner@example.com",
      ),
    ).toEqual({ allowed: true, status: 200, code: "ok" });
  });
});

import { describe, expect, it, vi } from "vitest";

import { ApiError, getActiveDiagnosticSession, messageForError } from "./api";

describe("diagnostic API helpers", () => {
  it("treats a missing active session as an empty state", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: {
              code: "active_session_not_found",
              message: "No active session.",
            },
          }),
          { status: 404, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    await expect(
      getActiveDiagnosticSession("algorithm", "0.1.0"),
    ).resolves.toBeNull();
    vi.unstubAllGlobals();
  });

  it("keeps server error messages available to the interface", () => {
    expect(messageForError(new ApiError(409, "conflict", "已有活动会话"))).toBe(
      "已有活动会话",
    );
  });
});

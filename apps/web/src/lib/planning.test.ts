import { describe, expect, it } from "vitest";

import { isCurrentDiagnosticProposal } from "./planning";

describe("isCurrentDiagnosticProposal", () => {
  it("rejects stale and rejected proposals", () => {
    expect(
      isCurrentDiagnosticProposal(
        {
          diagnostic_session_id: "older-diagnostic",
          status: "saved_preview",
        },
        "current-diagnostic",
      ),
    ).toBe(false);
    expect(
      isCurrentDiagnosticProposal(
        {
          diagnostic_session_id: "current-diagnostic",
          status: "rejected",
        },
        "current-diagnostic",
      ),
    ).toBe(false);
  });

  it("accepts a writable or saved proposal for the current diagnostic", () => {
    expect(
      isCurrentDiagnosticProposal(
        {
          diagnostic_session_id: "current-diagnostic",
          status: "draft",
        },
        "current-diagnostic",
      ),
    ).toBe(true);
    expect(
      isCurrentDiagnosticProposal(
        {
          diagnostic_session_id: "current-diagnostic",
          status: "saved_preview",
        },
        "current-diagnostic",
      ),
    ).toBe(true);
  });
});

import { describe, expect, it } from "vitest";

import {
  availableExperimentActions,
  experimentGateCopy,
  experimentReasonCopy,
} from "./experiments";

describe("experiment presentation", () => {
  it("keeps local readiness distinct from real action readiness", () => {
    expect(experimentGateCopy("local_ready").title).toContain("本地");
    expect(experimentGateCopy("action_ready").description).toContain("不会");
  });

  it("explains scoped evidence and review gaps", () => {
    expect(experimentReasonCopy("operation_verified_required")).toContain("verified");
    expect(
      experimentReasonCopy("review_flag_blocking:artifact:source_review_pending"),
    ).toContain("artifact");
  });

  it("does not expose transitions from terminal states", () => {
    expect(availableExperimentActions("completed")).toEqual([]);
    expect(availableExperimentActions("active")).toContain("paused");
  });
});

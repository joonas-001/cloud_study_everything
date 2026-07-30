import { describe, expect, it } from "vitest";

import {
  comparisonPaths,
  evidenceDimensions,
  isMonetizationGoal,
  readinessStatusCopy,
  reasonCodeCopy,
} from "./readiness";

describe("readiness presentation rules", () => {
  it("does not force exams or learning goals into monetization", () => {
    expect(isMonetizationGoal("exam")).toBe(false);
    expect(isMonetizationGoal("learning")).toBe(false);
    expect(readinessStatusCopy("not_applicable").title).toContain("不适用");
  });

  it("keeps stable reason codes understandable", () => {
    expect(reasonCodeCopy("evidence_dimension_missing:artifact")).toContain(
      "artifact",
    );
    expect(reasonCodeCopy("experiment_threshold_unconfirmed")).toContain(
      "最低证据",
    );
  });

  it("defensively reads evidence and comparison payloads", () => {
    expect(evidenceDimensions(null)).toEqual([]);
    expect(comparisonPaths(null)).toEqual([]);
  });
});

import { describe, expect, it } from "vitest";

import type {
  LearningActivityResponse,
  MasteryDimensionResponse,
  MasteryEvidenceItemResponse,
} from "@/generated/api-schema";

import {
  dimensionEvidence,
  evidenceActivityTitle,
  evidenceUpdatedAt,
} from "./evidence";

function evidence(overrides: Partial<MasteryEvidenceItemResponse> = {}): MasteryEvidenceItemResponse {
  return {
    activity_id: "activity-1",
    attempt_id: "attempt-1",
    capability_ids: ["p-control-flow"],
    created_at: "2026-08-12T08:00:00Z",
    criterion_id: "criterion-1",
    dimension: "understanding",
    id: "evidence-1",
    language: "none",
    method: "deterministic",
    result: "passed",
    review_flags: [],
    strength: "supported",
    superseded_at: null,
    ...overrides,
  };
}

describe("evidence center projections", () => {
  it("keeps dimensions scoped and excludes superseded records", () => {
    const current = evidence();
    const older = evidence({ id: "evidence-2", created_at: "2026-08-11T08:00:00Z" });
    const superseded = evidence({ id: "evidence-3", superseded_at: "2026-08-13T08:00:00Z" });
    const other = evidence({ id: "evidence-4", dimension: "operation" });

    expect(dimensionEvidence("understanding", [older, other, superseded, current])).toEqual([
      current,
      older,
    ]);
  });

  it("uses activity titles only when the current response contains them", () => {
    const activity = { id: "activity-1", title: "边界处理检查" } as LearningActivityResponse;
    expect(evidenceActivityTitle(evidence(), [activity])).toBe("边界处理检查");
    expect(evidenceActivityTitle(evidence({ activity_id: "missing" }), [activity])).toContain(
      "历史活动",
    );
  });

  it("reports the newest dimension update without inventing an aggregate", () => {
    const dimensions = [
      { updated_at: "2026-08-11T08:00:00Z" },
      { updated_at: "2026-08-12T08:00:00Z" },
    ] as MasteryDimensionResponse[];
    expect(evidenceUpdatedAt(dimensions)).toBe("2026-08-12T08:00:00Z");
    expect(evidenceUpdatedAt([])).toBeNull();
  });
});

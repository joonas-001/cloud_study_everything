import { describe, expect, it } from "vitest";

import { getPlatformMilestones } from "./platform";

describe("getPlatformMilestones", () => {
  it("keeps the first milestone focused on governed content", () => {
    const milestones = getPlatformMilestones();

    expect(milestones).toHaveLength(3);
    expect(milestones[0]?.title).toBe("可信内容边界");
  });
});

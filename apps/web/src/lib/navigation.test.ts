import { describe, expect, it } from "vitest";

import { getActiveMobileSection, getActiveSection } from "./navigation";

describe("navigation mapping", () => {
  it.each([
    ["/", "today"],
    ["/diagnostic", "learning"],
    ["/learning/runs/example", "learning"],
    ["/evidence", "evidence"],
    ["/readiness", "goals"],
    ["/market-research", "goals"],
    ["/experiments", "goals"],
    ["/inbox", "inbox"],
    ["/settings", "settings"],
  ])("maps %s to %s", (pathname, section) => {
    expect(getActiveSection(pathname)).toBe(section);
  });

  it("maps goal and settings routes into mobile More", () => {
    expect(getActiveMobileSection("/goals")).toBe("more");
    expect(getActiveMobileSection("/settings")).toBe("more");
  });

  it("does not treat a shared text prefix as a route segment", () => {
    expect(getActiveSection("/learning-old")).toBeNull();
  });

  it("keeps the More route selected on mobile without selecting a desktop section", () => {
    expect(getActiveSection("/more")).toBeNull();
    expect(getActiveMobileSection("/more")).toBe("more");
  });
});

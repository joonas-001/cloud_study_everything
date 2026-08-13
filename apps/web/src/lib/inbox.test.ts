import { describe, expect, it } from "vitest";

import type { NotificationResponse } from "@/generated/api-schema";

import {
  classifyNotification,
  notificationHref,
  notificationScope,
  unreadNotificationCount,
} from "./inbox";

function notification(
  overrides: Partial<NotificationResponse> = {},
): NotificationResponse {
  return {
    archived_at: null,
    category: "planning",
    created_at: "2026-08-12T08:00:00Z",
    email_status: null,
    id: "notification-1",
    message: "message",
    read_at: null,
    related_id: "proposal-1",
    related_type: "planning_proposal",
    severity: "info",
    title: "title",
    ...overrides,
  };
}

describe("inbox classification", () => {
  it("gives explicit decision and action severities precedence", () => {
    expect(classifyNotification(notification({ severity: "required" }))).toBe(
      "confirmation",
    );
    expect(
      classifyNotification(
        notification({ category: "source_update", severity: "action_required" }),
      ),
    ).toBe("action");
  });

  it("maps only known managed categories and does not infer unknown meanings", () => {
    expect(classifyNotification(notification())).toBe("change");
    expect(classifyNotification(notification({ category: "evidence_update" }))).toBe(
      "change",
    );
    expect(classifyNotification(notification({ category: "source_check" }))).toBe(
      "system",
    );
    expect(classifyNotification(notification({ category: "security" }))).toBe(
      "unclassified",
    );
  });

  it("counts real unread records and exposes only known destinations", () => {
    const unread = notification();
    const read = notification({ id: "notification-2", read_at: "2026-08-12T09:00:00Z" });
    expect(unreadNotificationCount([unread, read])).toBe(1);
    expect(notificationScope(unread)).toBe("学习规划");
    expect(notificationHref(unread)).toBe("/learning");
    expect(notificationHref(notification({ category: "security", related_type: null }))).toBeNull();
  });
});

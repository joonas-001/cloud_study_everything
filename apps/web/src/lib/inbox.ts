import type { NotificationResponse } from "@/generated/api-schema";

export type InboxCategoryId =
  | "confirmation"
  | "action"
  | "change"
  | "system"
  | "unclassified";

export type InboxCategory = {
  id: InboxCategoryId;
  title: string;
  description: string;
};

export const INBOX_CATEGORIES: readonly InboxCategory[] = [
  {
    id: "confirmation",
    title: "需要确认",
    description: "必须由你明确决定后才能继续的事项。",
  },
  {
    id: "action",
    title: "需要行动",
    description: "已有确定下一步、等待你处理的事项。",
  },
  {
    id: "change",
    title: "信息变化",
    description: "规划、证据或受管来源发生的可追溯变化。",
  },
  {
    id: "system",
    title: "系统状态",
    description: "来源检查、邮件通道等运行状态。",
  },
] as const;

export const UNCLASSIFIED_CATEGORY: InboxCategory = {
  id: "unclassified",
  title: "未分类",
  description: "当前受管映射无法可靠判断，保留原始类别而不臆测。",
};

const CHANGE_CATEGORIES = new Set(["planning", "source_update", "evidence_update"]);
const SYSTEM_CATEGORIES = new Set(["source_check", "email_test"]);

export function classifyNotification(notification: NotificationResponse): InboxCategoryId {
  if (notification.severity === "required") {
    return "confirmation";
  }
  if (notification.severity === "action_required") {
    return "action";
  }
  if (CHANGE_CATEGORIES.has(notification.category)) {
    return "change";
  }
  if (SYSTEM_CATEGORIES.has(notification.category)) {
    return "system";
  }
  return "unclassified";
}

export function unreadNotificationCount(notifications: readonly NotificationResponse[]): number {
  return notifications.filter((notification) => notification.read_at === null).length;
}

export function notificationScope(notification: NotificationResponse): string {
  const labels: Record<string, string> = {
    planning_proposal: "学习规划",
    source_check_run: "来源检查",
    source_change_candidate: "来源变化候选",
    learning_run: "学习执行与证据",
  };
  if (notification.related_type && labels[notification.related_type]) {
    return labels[notification.related_type];
  }
  if (notification.category === "email_test") {
    return "通知设置";
  }
  return notification.related_type
    ? `未识别范围：${notification.related_type}`
    : "未提供关联范围";
}

export function notificationHref(notification: NotificationResponse): string | null {
  if (
    notification.related_type === "planning_proposal" ||
    notification.related_type === "source_check_run" ||
    notification.related_type === "source_change_candidate"
    || notification.related_type === "learning_run"
  ) {
    return "/learning";
  }
  if (notification.category === "email_test") {
    return "/settings";
  }
  return null;
}

export function formatNotificationTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "时间不可用";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export const INBOX_UPDATED_EVENT = "cloud-study:inbox-updated";

export function announceInboxUpdated(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(INBOX_UPDATED_EVENT));
  }
}

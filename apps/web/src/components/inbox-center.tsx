"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import type { NotificationResponse } from "@/generated/api-schema";
import { PageHeader } from "@/components/page-header";
import { StatusMessage } from "@/components/status-message";
import { getNotifications, markNotificationRead, messageForError, processEmailOutbox } from "@/lib/api";
import {
  announceInboxUpdated,
  classifyNotification,
  formatNotificationTime,
  INBOX_CATEGORIES,
  notificationHref,
  notificationScope,
  UNCLASSIFIED_CATEGORY,
  unreadNotificationCount,
} from "@/lib/inbox";

export function InboxCenter() {
  const [notifications, setNotifications] = useState<Array<NotificationResponse>>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      await processEmailOutbox().catch(() => null);
      const next = await getNotifications();
      setNotifications(next);
      announceInboxUpdated();
    } catch (reason: unknown) {
      setError(messageForError(reason));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    processEmailOutbox()
      .catch(() => null)
      .then(() => getNotifications())
      .then((next) => {
        if (active) {
          setNotifications(next);
          announceInboxUpdated();
        }
      })
      .catch((reason: unknown) => {
        if (active) {
          setError(messageForError(reason));
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, []);

  const unreadCount = unreadNotificationCount(notifications);
  const categories = useMemo(() => {
    const managed = INBOX_CATEGORIES.map((category) => ({
      ...category,
      notifications: notifications.filter(
        (notification) => classifyNotification(notification) === category.id,
      ),
    }));
    const unclassified = notifications.filter(
      (notification) => classifyNotification(notification) === "unclassified",
    );
    return unclassified.length > 0
      ? [...managed, { ...UNCLASSIFIED_CATEGORY, notifications: unclassified }]
      : managed;
  }, [notifications]);

  async function markRead(notificationId: string) {
    setBusyId(notificationId);
    setError(null);
    try {
      const updated = await markNotificationRead(notificationId);
      setNotifications((current) =>
        current.map((notification) =>
          notification.id === updated.id ? updated : notification,
        ),
      );
      announceInboxUpdated();
    } catch (reason: unknown) {
      setError(messageForError(reason));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Inbox · 7C"
        title="把需要了解、确认或处理的变化放在同一个地方。"
        description="收件箱读取真实站内通知，并按受管字段分类；未知类别会明确保留为未分类，不根据标题臆测。"
        context={[
          {
            label: "未读状态",
            value: loading ? "读取中" : error ? "读取失败" : `${unreadCount} 条未读`,
            tone: unreadCount > 0 || error ? "warning" : "positive",
          },
          { label: "通知总数", value: loading ? "读取中" : `${notifications.length} 条` },
          { label: "通知偏好", value: "在设置中管理" },
        ]}
        actions={
          <>
            <button className="primary-button" type="button" disabled={loading} onClick={() => void load()}>
              刷新收件箱
            </button>
            <Link className="secondary-link" href="/settings">
              管理通知偏好
            </Link>
          </>
        }
      />

      {error ? (
        <StatusMessage tone="error" title="收件箱读取失败">
          {error}
        </StatusMessage>
      ) : null}

      <section className="m7-hub-section" aria-labelledby="inbox-categories-title" aria-busy={loading}>
        <div className="m7-section-heading">
          <div>
            <span className="eyebrow">Message taxonomy</span>
            <h2 id="inbox-categories-title">真实站内通知</h2>
          </div>
          <p>已读只表示你看过这条消息，不代表关联任务完成、证据成立或阻断解除。</p>
        </div>

        {loading ? (
        <div className="panel loading-panel" role="status" aria-live="polite" aria-busy="true">
            <span className="loading-dot" aria-hidden="true" />
            正在读取站内通知……
          </div>
        ) : notifications.length === 0 ? (
          <div className="m7-empty-state">
            <h3>目前没有站内通知</h3>
            <p>规划、证据和来源流程产生变化后会在这里留下可追溯记录。</p>
            <Link href="/learning">进入学习工作区</Link>
          </div>
        ) : (
          <div className="inbox-groups">
            {categories.map((category) => (
              <section className="inbox-group" aria-labelledby={`inbox-${category.id}`} key={category.id}>
                <header>
                  <div>
                    <h3 id={`inbox-${category.id}`}>{category.title}</h3>
                    <p>{category.description}</p>
                  </div>
                  <span>{category.notifications.length} 条</span>
                </header>
                {category.notifications.length === 0 ? (
                  <p className="inbox-group__empty">当前没有此类事项。</p>
                ) : (
                  <ol>
                    {category.notifications.map((notification) => {
                      const href = notificationHref(notification);
                      return (
                        <li className={notification.read_at ? "is-read" : "is-unread"} key={notification.id}>
                          <div className="inbox-message__meta">
                            <span>{notification.read_at ? "已读" : "未读"}</span>
                            <span>{formatNotificationTime(notification.created_at)}</span>
                            <span>范围：{notificationScope(notification)}</span>
                            {category.id === "unclassified" ? (
                              <span>原始类别：{notification.category}</span>
                            ) : null}
                          </div>
                          <h4>{notification.title}</h4>
                          <p>{notification.message}</p>
                          <div className="inbox-message__actions">
                            {href ? <Link href={href}>查看关联页面</Link> : <span>没有可靠的关联入口</span>}
                            {!notification.read_at ? (
                              <button
                                className="text-button"
                                type="button"
                                disabled={busyId === notification.id}
                                onClick={() => void markRead(notification.id)}
                              >
                                {busyId === notification.id ? "正在标记…" : "标记已读"}
                              </button>
                            ) : null}
                          </div>
                        </li>
                      );
                    })}
                  </ol>
                )}
              </section>
            ))}
          </div>
        )}
      </section>
    </>
  );
}

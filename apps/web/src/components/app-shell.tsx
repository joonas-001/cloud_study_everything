"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import type { AuthenticationSessionResponse } from "@/generated/api-schema";

import {
  getActiveMobileSection,
  getActiveSection,
  MOBILE_NAVIGATION,
  PRIMARY_NAVIGATION,
} from "@/lib/navigation";
import {
  cancelAccountDeletion,
  getAuthenticationSession,
  getNotifications,
  logoutAllAuthenticationSessions,
} from "@/lib/api";
import { INBOX_UPDATED_EVENT, unreadNotificationCount } from "@/lib/inbox";

function InboxState({ count, status }: Readonly<{ count: number | null; status: "loading" | "ready" | "error" }>) {
  const label =
    status === "loading"
      ? "读取中"
      : status === "error"
        ? "不可用"
        : count === 0
          ? "无未读"
          : `${count} 未读`;
  return (
    <span className="nav-item__state" aria-label={`收件箱未读状态：${label}`}>
      {label}
    </span>
  );
}

export function AppShell({ children }: Readonly<{ children: ReactNode }>) {
  const pathname = usePathname();
  const [inboxCount, setInboxCount] = useState<number | null>(null);
  const [inboxStatus, setInboxStatus] = useState<"loading" | "ready" | "error">("loading");
  const [authSession, setAuthSession] = useState<AuthenticationSessionResponse | null>(null);
  const [authStatus, setAuthStatus] = useState<"loading" | "ready" | "error">("loading");
  const [authActionPending, setAuthActionPending] = useState(false);
  const activeSection = getActiveSection(pathname);
  const activeMobileSection = getActiveMobileSection(pathname);
  const activeLabel =
    pathname === "/more"
      ? "更多"
      : (PRIMARY_NAVIGATION.find((item) => item.id === activeSection)?.label ?? "云奕学");

  const refreshInboxState = useCallback(async () => {
    try {
      const notifications = await getNotifications();
      setInboxCount(unreadNotificationCount(notifications));
      setInboxStatus("ready");
    } catch {
      setInboxCount(null);
      setInboxStatus("error");
    }
  }, []);

  useEffect(() => {
    let active = true;
    getAuthenticationSession()
      .then((session) => {
        if (active) {
          setAuthSession(session);
          setAuthStatus("ready");
        }
      })
      .catch(() => {
        if (active) setAuthStatus("error");
      });
    return () => {
      active = false;
    };
  }, [pathname]);

  useEffect(() => {
    let active = true;
    getNotifications()
      .then((notifications) => {
        if (active) {
          setInboxCount(unreadNotificationCount(notifications));
          setInboxStatus("ready");
        }
      })
      .catch(() => {
        if (active) {
          setInboxCount(null);
          setInboxStatus("error");
        }
      });
    const handleUpdate = () => void refreshInboxState();
    window.addEventListener(INBOX_UPDATED_EVENT, handleUpdate);
    return () => {
      active = false;
      window.removeEventListener(INBOX_UPDATED_EVENT, handleUpdate);
    };
  }, [pathname, refreshInboxState]);

  const logoutAll = async () => {
    setAuthActionPending(true);
    try {
      await logoutAllAuthenticationSessions();
      setAuthSession((current) =>
        current ? { ...current, authenticated: false } : current,
      );
      setInboxCount(null);
      setInboxStatus("error");
    } finally {
      setAuthActionPending(false);
    }
  };

  const restoreDeletionPendingAccount = async () => {
    setAuthActionPending(true);
    try {
      await cancelAccountDeletion();
      const session = await getAuthenticationSession();
      setAuthSession(session);
    } finally {
      setAuthActionPending(false);
    }
  };

  if (
    authStatus === "ready" &&
    authSession?.mode !== "legacy_owner" &&
    !authSession?.authenticated
  ) {
    return (
      <main className="authentication-boundary" id="main-content">
        <p className="eyebrow">受控认证候选</p>
        <h1>需要登录</h1>
        <p>当前页面只接受已完成 OIDC 与 MFA 校验的短期应用会话。</p>
        <p className="boundary-note">
          9C 尚未连接真实 Clerk 应用，也未开放注册、真实邀请或账号恢复后门。
        </p>
      </main>
    );
  }

  if (
    authStatus === "ready" &&
    authSession?.account_status === "deletion_pending"
  ) {
    return (
      <main className="authentication-boundary" id="main-content">
        <p className="eyebrow">账号删除等待期</p>
        <h1>学习数据入口已暂停</h1>
        <p>当前会话只能撤销删除；普通学习、设置和证据入口保持关闭。</p>
        <button
          className="primary-button"
          disabled={authActionPending}
          onClick={() => void restoreDeletionPendingAccount()}
          type="button"
        >
          {authActionPending ? "处理中…" : "撤销删除申请"}
        </button>
      </main>
    );
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        跳到主要内容
      </a>

      <aside className="desktop-sidebar" aria-label="应用导航">
        <Link className="app-wordmark" href="/" aria-label="云奕学今日">
          <span>云奕学</span>
          <small>个人学习系统</small>
        </Link>
        <nav className="desktop-navigation" aria-label="主导航">
          <ul>
            {PRIMARY_NAVIGATION.map((item) => (
              <li className={item.id === "settings" ? "nav-item--settings" : undefined} key={item.id}>
                <Link
                  className="desktop-nav-link"
                  aria-current={activeSection === item.id ? "page" : undefined}
                  href={item.href}
                >
                  <span>{item.label}</span>
                  {item.id === "inbox" ? (
                    <InboxState count={inboxCount} status={inboxStatus} />
                  ) : null}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <div className="sidebar-boundary">
          <p>完成进度与掌握证据始终分开显示。</p>
          {authSession?.mode !== "legacy_owner" && authSession?.authenticated ? (
            <div className="session-summary">
              <span>受控会话 · {authSession.role === "owner_operator" ? "所有者" : "用户"}</span>
              <button
                className="text-button"
                disabled={authActionPending}
                onClick={() => void logoutAll()}
                type="button"
              >
                退出所有设备
              </button>
            </div>
          ) : null}
        </div>
      </aside>

      <div className="app-content">
        <div className="mobile-context-bar">
          <Link href="/">云奕学</Link>
          <span aria-label={`当前一级区域：${activeLabel}`}>{activeLabel}</span>
        </div>
        {children}
      </div>

      <nav className="mobile-navigation" aria-label="移动端主导航">
        <ul>
          {MOBILE_NAVIGATION.map((item) => (
            <li key={item.id}>
              <Link
                aria-current={activeMobileSection === item.id ? "page" : undefined}
                href={item.href}
              >
                <span className="mobile-nav-mark" aria-hidden="true">
                  {item.shortLabel}
                </span>
                <span>{item.label}</span>
                {item.id === "inbox" ? (
                  <span className="visually-hidden">
                    ，收件箱未读状态：
                    {inboxStatus === "loading"
                      ? "读取中"
                      : inboxStatus === "error"
                        ? "不可用"
                        : inboxCount === 0
                          ? "无未读"
                          : `${inboxCount} 条未读`}
                  </span>
                ) : null}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
    </div>
  );
}

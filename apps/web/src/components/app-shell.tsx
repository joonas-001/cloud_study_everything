"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import {
  getActiveMobileSection,
  getActiveSection,
  MOBILE_NAVIGATION,
  PRIMARY_NAVIGATION,
} from "@/lib/navigation";

function InboxState() {
  return (
    <span className="nav-item__state" aria-label="收件箱未读状态：尚未汇总">
      未汇总
    </span>
  );
}

export function AppShell({ children }: Readonly<{ children: ReactNode }>) {
  const pathname = usePathname();
  const activeSection = getActiveSection(pathname);
  const activeMobileSection = getActiveMobileSection(pathname);
  const activeLabel =
    pathname === "/more"
      ? "更多"
      : (PRIMARY_NAVIGATION.find((item) => item.id === activeSection)?.label ?? "云奕学");

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
                  {item.id === "inbox" ? <InboxState /> : null}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <p className="sidebar-boundary">完成进度与掌握证据始终分开显示。</p>
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
                  <span className="visually-hidden">，未读状态尚未汇总</span>
                ) : null}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
    </div>
  );
}

import Link from "next/link";

import { SystemSettings } from "@/components/system-settings";

export default function SettingsPage() {
  return (
    <main className="page settings-page">
      <nav className="top-nav" aria-label="页面导航">
        <Link className="wordmark" href="/">
          云奕学
        </Link>
        <div className="nav-links">
          <Link href="/diagnostic">诊断</Link>
          <Link href="/learning">学习面板</Link>
          <Link href="/readiness">目标与准备度</Link>
          <Link href="/market-research">市场研究</Link>
          <Link href="/experiments">就业实验</Link>
          <Link aria-current="page" href="/settings">
            设置
          </Link>
        </div>
      </nav>
      <header className="page-intro">
        <div className="eyebrow">Local control</div>
        <h1>外发之前，先把边界说清楚。</h1>
        <p>
          邮件和真实 AI 默认不会自动启用。密钥只保存为 Windows 凭据引用，SQLite 和页面不会返回原文。
        </p>
      </header>
      <SystemSettings />
    </main>
  );
}

import Link from "next/link";

import { ReadinessPanel } from "@/components/readiness-panel";

export default function ReadinessPage() {
  return (
    <main className="page readiness-page">
      <nav className="top-nav" aria-label="页面导航">
        <Link className="wordmark" href="/">
          云奕学
        </Link>
        <div className="nav-links">
          <Link href="/diagnostic">诊断</Link>
          <Link href="/learning">学习面板</Link>
          <Link aria-current="page" href="/readiness">
            目标与准备度
          </Link>
          <Link href="/settings">设置</Link>
        </div>
      </nav>
      <header className="page-intro">
        <div className="eyebrow">Goal before monetization</div>
        <h1>目标由你选择，系统只在证据允许时比较。</h1>
        <p>
          第五里程碑 5A
          只使用本地能力证据和显著标记的合成市场夹具。考试或纯学习目标不会被强制导向求职。
        </p>
      </header>
      <ReadinessPanel />
    </main>
  );
}

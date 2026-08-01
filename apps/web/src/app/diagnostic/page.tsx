import Link from "next/link";

import { DiagnosticInterview } from "@/components/diagnostic-interview";

export default function DiagnosticPage() {
  return (
    <main className="page diagnostic-page">
      <nav className="top-nav" aria-label="页面导航">
        <Link className="wordmark" href="/">
          云奕学
        </Link>
        <div className="nav-links">
          <Link aria-current="page" href="/diagnostic">
            诊断
          </Link>
          <Link href="/learning">学习面板</Link>
          <Link href="/readiness">目标与准备度</Link>
          <Link href="/market-research">市场研究</Link>
          <Link href="/experiments">就业实验</Link>
          <Link href="/settings">设置</Link>
        </div>
      </nav>
      <header className="page-intro">
        <div className="eyebrow">Diagnostic preview</div>
        <h1>先看清起点，再安排路径。</h1>
        <p>
          这是一条受限的算法技能包诊断预览，用来验证递进提问、分支、修正和审计记录。
        </p>
      </header>
      <DiagnosticInterview />
    </main>
  );
}

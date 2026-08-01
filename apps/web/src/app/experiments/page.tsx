import Link from "next/link";

import { ExperimentPanel } from "@/components/experiment-panel";

export default function ExperimentsPage() {
  return (
    <main className="page experiments-page">
      <nav className="top-nav" aria-label="页面导航">
        <Link className="wordmark" href="/">
          云奕学
        </Link>
        <div className="nav-links">
          <Link href="/diagnostic">诊断</Link>
          <Link href="/learning">学习面板</Link>
          <Link href="/readiness">目标与准备度</Link>
          <Link href="/market-research">市场研究</Link>
          <Link aria-current="page" href="/experiments">
            就业实验
          </Link>
          <Link href="/settings">设置</Link>
        </div>
      </nav>
      <header className="page-intro">
        <div className="eyebrow">Evidence-gated experiment · 5C</div>
        <h1>先验证能力范围，再记录你亲自完成的求职实验。</h1>
        <p>
          首版只启用初级 C++ 后端与算法应用就业方向。系统负责本地计划、门禁、结果和复盘，
          不会自动投递、联系、登录平台、签约或交易。
        </p>
      </header>
      <ExperimentPanel />
    </main>
  );
}

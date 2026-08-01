import Link from "next/link";

import { LearningDashboard } from "@/components/learning-dashboard";

export default function LearningPage() {
  return (
    <main className="page learning-page">
      <nav className="top-nav" aria-label="页面导航">
        <Link className="wordmark" href="/">
          云奕学
        </Link>
        <div className="nav-links">
          <Link href="/diagnostic">诊断</Link>
          <Link aria-current="page" href="/learning">
            学习面板
          </Link>
          <Link href="/readiness">目标与准备度</Link>
          <Link href="/market-research">市场研究</Link>
          <Link href="/experiments">就业实验</Link>
          <Link href="/settings">设置</Link>
        </div>
      </nav>
      <header className="page-intro">
        <div className="eyebrow">Evidence-led learning</div>
        <h1>计划可以调整，依据必须留下。</h1>
        <p>
          当前页面验证规划选择、学习活动、隔离代码运行、追加修订、六维证据和固定间隔复习。
        </p>
      </header>
      <LearningDashboard skillId="algorithm" skillVersion="0.2.1" />
    </main>
  );
}

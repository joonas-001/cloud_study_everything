import Link from "next/link";

import { MarketResearchPanel } from "@/components/market-research-panel";

export default function MarketResearchPage() {
  return (
    <main className="page market-research-page">
      <nav className="top-nav" aria-label="页面导航">
        <Link className="wordmark" href="/">
          云奕学
        </Link>
        <div className="nav-links">
          <Link href="/diagnostic">诊断</Link>
          <Link href="/learning">学习面板</Link>
          <Link href="/readiness">目标与准备度</Link>
          <Link aria-current="page" href="/market-research">
            市场研究
          </Link>
          <Link href="/settings">设置</Link>
        </div>
      </nav>
      <header className="page-intro">
        <div className="eyebrow">Governed market research · 5B</div>
        <h1>先核验来源与费用，再让 AI 做有限综合。</h1>
        <p>
          真实市场研究仅限中国大陆已确认范围、官方白名单和
          deepseek-v4-flash。所有外发均需逐次确认，结果必须人工复核。
        </p>
      </header>
      <MarketResearchPanel />
    </main>
  );
}

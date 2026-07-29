import Link from "next/link";

import { getPlatformMilestones } from "@/lib/platform";

export default function Home() {
  const milestones = getPlatformMilestones();

  return (
    <main className="page">
      <nav className="top-nav" aria-label="页面导航">
        <span className="wordmark">云奕学</span>
        <div className="nav-links">
          <Link href="/diagnostic">诊断</Link>
          <Link href="/learning">学习面板</Link>
          <Link href="/readiness">目标与准备度</Link>
          <Link href="/settings">设置</Link>
        </div>
      </nav>
      <header className="hero">
        <div className="eyebrow">Evidence before confidence</div>
        <h1>让每一步学习，都留下可信的掌握证据。</h1>
        <p>
          云奕学从诊断真实基础开始，逐步连接学习、实践、作品与复习。当前版本专注验证最小闭环。
        </p>
        <Link className="primary-button" href="/diagnostic">
          进入算法诊断预览
        </Link>
        <Link className="secondary-link" href="/learning">
          查看学习面板
        </Link>
        <Link className="secondary-link" href="/readiness">
          选择目标并查看准备度
        </Link>
      </header>
      <div className="status">开发状态：第四里程碑 4A 已合并 · 第五里程碑 5A 实施中</div>

      <section className="grid" aria-label="当前基础能力">
        {milestones.map((milestone) => (
          <article className="card" key={milestone.title}>
            <h2>{milestone.title}</h2>
            <p>{milestone.description}</p>
          </article>
        ))}
      </section>

      <aside className="notice">
        算法技能包 0.2.0 目前仍是草稿。诊断和学习执行只使用本地确定性流程，
        不会调用外部 AI、执行代码或生成正式掌握结论。5A 只提供显著标记的合成比较。
      </aside>
    </main>
  );
}

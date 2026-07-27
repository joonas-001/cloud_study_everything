import Link from "next/link";

import { getPlatformMilestones } from "@/lib/platform";

export default function Home() {
  const milestones = getPlatformMilestones();

  return (
    <main className="page">
      <nav className="top-nav" aria-label="页面导航">
        <span className="wordmark">云奕学</span>
        <span>本地验证环境</span>
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
      </header>
      <div className="status">开发状态：诊断访谈里程碑</div>

      <section className="grid" aria-label="当前基础能力">
        {milestones.map((milestone) => (
          <article className="card" key={milestone.title}>
            <h2>{milestone.title}</h2>
            <p>{milestone.description}</p>
          </article>
        ))}
      </section>

      <aside className="notice">
        算法技能包目前仍是草稿。诊断只能使用本地确定性流程，不会调用外部
        AI，也不会生成正式学习计划、掌握结论或变现建议。
      </aside>
    </main>
  );
}

import { getPlatformMilestones } from "@/lib/platform";

export default function Home() {
  const milestones = getPlatformMilestones();

  return (
    <main className="page">
      <h1>云奕学</h1>
      <p>当前功能骨架用于验证项目结构、数据迁移、契约和技能包治理。</p>
      <div className="status">开发状态：基础设施里程碑</div>

      <section className="grid" aria-label="当前基础能力">
        {milestones.map((milestone) => (
          <article className="card" key={milestone.title}>
            <h2>{milestone.title}</h2>
            <p>{milestone.description}</p>
          </article>
        ))}
      </section>

      <aside className="notice">
        算法技能包目前仍是草稿，只用于验证注册表与完整性门禁；它尚未获准生成正式学习计划。
      </aside>
    </main>
  );
}

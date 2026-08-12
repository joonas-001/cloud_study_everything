import Link from "next/link";

import { PageHeader } from "@/components/page-header";

export default function Home() {
  return (
    <main id="main-content" tabIndex={-1} className="page today-page">
      <PageHeader
        eyebrow="Today · 7B shell"
        title="今天从最明确的一步开始。"
        description="当前阶段先建立稳定入口；跨记录的今日聚合将在 7C 接入，不会用占位数据冒充真实任务或状态。"
        context={[
          { label: "技能包", value: "algorithm@0.2.2" },
          { label: "今日聚合", value: "尚未接入", tone: "warning" },
          { label: "证据边界", value: "完成不等于掌握" },
        ]}
        actions={
          <Link className="primary-button" href="/learning">
            进入现有学习工作区
          </Link>
        }
      />

      <section className="m7-overview" aria-labelledby="today-overview-title">
        <div className="m7-section-heading">
          <div>
            <span className="eyebrow">Current view</span>
            <h2 id="today-overview-title">今日概览</h2>
          </div>
          <p>7B 只提供准确入口，7C 才会建立跨记录聚合。</p>
        </div>
        <div className="m7-overview-grid">
          <article className="m7-overview-card m7-overview-card--primary">
            <span className="m7-card-kicker">当前任务</span>
            <h3>从已有学习执行继续</h3>
            <p>本页尚未读取活动执行记录。进入学习工作区查看已锁定规划、今日活动与完成标准。</p>
            <Link href="/learning">查看学习工作区</Link>
          </article>
          <article className="m7-overview-card">
            <span className="m7-card-kicker">到期复习</span>
            <h3>尚未汇总到今日</h3>
            <p>现有延迟复习仍保留在对应学习执行记录中，7B 不推断是否已经到期。</p>
            <Link href="/learning">查看复习记录</Link>
          </article>
          <article className="m7-overview-card">
            <span className="m7-card-kicker">阻断事项</span>
            <h3>按能力范围查看门禁</h3>
            <p>学习阻断和目标实验门禁仍由原有页面确定，不把局部状态外推为整门技能结论。</p>
            <Link href="/goals">进入目标与行动</Link>
          </article>
          <article className="m7-overview-card">
            <span className="m7-card-kicker">最近变化</span>
            <h3>统一变化流尚未接入</h3>
            <p>来源候选和站内通知仍在原位置；收件箱当前明确展示这一限制。</p>
            <Link href="/inbox">查看收件箱边界</Link>
          </article>
        </div>
      </section>
    </main>
  );
}

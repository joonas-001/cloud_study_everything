import Link from "next/link";

import { PageHeader } from "@/components/page-header";

export default function GoalsPage() {
  return (
    <main id="main-content" tabIndex={-1} className="page goals-page">
      <PageHeader
        eyebrow="Goals and actions"
        title="先明确目标，再决定哪些比较和行动适用。"
        description="这里把准备度、市场研究和就业实验放回同一个目标上下文；原有页面与业务边界保持不变。"
        context={[
          { label: "当前目标", value: "以已保存选择为准" },
          { label: "自动外部动作", value: "不执行" },
          { label: "收入承诺", value: "不提供" },
        ]}
      />

      <section className="m7-hub-section" aria-labelledby="goal-tools-title">
        <div className="m7-section-heading">
          <div>
            <span className="eyebrow">Existing capabilities</span>
            <h2 id="goal-tools-title">目标工具</h2>
          </div>
          <p>7B 只重组入口，不合并或重算现有记录。</p>
        </div>
        <div className="m7-link-grid">
          <Link href="/readiness">
            <span>01</span>
            <strong>目标与准备度</strong>
            <small>选择就业、考试、纯学习或其他目标，并查看证据允许的比较。</small>
          </Link>
          <Link href="/market-research">
            <span>02</span>
            <strong>市场研究</strong>
            <small>在官方来源、费用硬上限和逐次确认下进行受限研究。</small>
          </Link>
          <Link href="/experiments">
            <span>03</span>
            <strong>就业实验</strong>
            <small>依据精确能力范围评估门禁，记录用户亲自在产品外完成的动作。</small>
          </Link>
        </div>
      </section>
    </main>
  );
}

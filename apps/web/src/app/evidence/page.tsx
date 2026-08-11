import Link from "next/link";

import { PageHeader } from "@/components/page-header";

const dimensions = ["知识理解", "操作能力", "迁移能力", "作品证据", "保持程度", "纠错能力"];

export default function EvidencePage() {
  return (
    <main id="main-content" tabIndex={-1} className="page evidence-page">
      <PageHeader
        eyebrow="Evidence center · 7B shell"
        title="证据说明能力范围，也说明仍不能证明什么。"
        description="7B 先建立独立证据入口。跨学习执行、真人评审和作品记录的汇总将在 7D 接入，本页不会把未读取的数据展示为无证据。"
        context={[
          { label: "汇总状态", value: "尚未接入", tone: "warning" },
          { label: "展示维度", value: "六维" },
          { label: "整体掌握", value: "不作无限范围结论" },
        ]}
        actions={
          <Link className="primary-button" href="/learning">
            查看现有执行证据
          </Link>
        }
      />

      <section className="m7-hub-section" aria-labelledby="evidence-dimensions-title">
        <div className="m7-section-heading">
          <div>
            <span className="eyebrow">Six dimensions</span>
            <h2 id="evidence-dimensions-title">六维证据中心入口</h2>
          </div>
          <p>待 7D 接入适用范围、等级、日期、有效期、验证方式、缺口和各类待办。</p>
        </div>
        <div className="m7-dimension-grid">
          {dimensions.map((dimension) => (
            <article key={dimension}>
              <h3>{dimension}</h3>
              <p>跨记录汇总尚未接入；请在对应学习执行中查看当前原始证据。</p>
              <span>未汇总不是“无证据”</span>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}

import { MarketResearchPanel } from "@/components/market-research-panel";
import { PageHeader } from "@/components/page-header";

export default function MarketResearchPage() {
  return (
    <main id="main-content" tabIndex={-1} className="page market-research-page">
      <PageHeader
        eyebrow="Goals · Governed market research"
        title="先核验来源与费用，再让 AI 做有限综合。"
        description="真实市场研究仅限中国大陆已确认范围、官方白名单和 deepseek-v4-flash。所有外发均需逐次确认，结果必须人工复核。"
        context={[
          { label: "一级区域", value: "目标与行动" },
          { label: "模型", value: "deepseek-v4-flash" },
          { label: "费用", value: "受日/月/单次硬门禁" },
        ]}
      />
      <MarketResearchPanel />
    </main>
  );
}

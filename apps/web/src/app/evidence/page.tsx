import { EvidenceCenter } from "@/components/evidence-center";
import { PageHeader } from "@/components/page-header";

export default function EvidencePage() {
  return (
    <main id="main-content" tabIndex={-1} className="page evidence-page">
      <PageHeader
        eyebrow="Evidence center · milestone 8E"
        title="看见证据，也看见精确范围与限制。"
        description="六维中心读取最新学习执行的真实证据；能力档案进一步按精确版本和能力 ID 展示验证方式、时效、学习分析与可导出边界。"
        context={[
          { label: "汇总范围", value: "单次执行 × 精确版本" },
          { label: "档案视图", value: "JSON / CSV / 打印" },
          { label: "整体掌握", value: "不作无限范围结论" },
        ]}
      />
      <EvidenceCenter skillId="algorithm" skillVersion="0.2.2" />
    </main>
  );
}

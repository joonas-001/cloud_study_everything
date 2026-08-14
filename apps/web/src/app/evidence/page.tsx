import { EvidenceCenter } from "@/components/evidence-center";
import { PageHeader } from "@/components/page-header";

export default function EvidencePage() {
  return (
    <main id="main-content" tabIndex={-1} className="page evidence-page">
      <PageHeader
        eyebrow="Evidence center · milestone 7D"
        title="看见证据，也看见证据的边界。"
        description="六维中心读取最新学习执行的真实证据，并把等级、记录、待办和独立评审分开呈现。"
        context={[
          { label: "汇总范围", value: "最新学习执行" },
          { label: "展示维度", value: "六维" },
          { label: "整体掌握", value: "不作无限范围结论" },
        ]}
      />
      <EvidenceCenter skillId="algorithm" skillVersion="0.2.2" />
    </main>
  );
}

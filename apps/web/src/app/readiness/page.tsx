import { PageHeader } from "@/components/page-header";
import { ReadinessPanel } from "@/components/readiness-panel";

export default function ReadinessPage() {
  return (
    <main id="main-content" tabIndex={-1} className="page readiness-page">
      <PageHeader
        eyebrow="Goals · Readiness"
        title="目标由你选择，系统只在证据允许时比较。"
        description="5A 仍只使用本地能力证据和显著标记的合成市场夹具。5B 的真实研究记录不会自动替换 5A 结果；考试或纯学习目标也不会被强制导向求职。"
        context={[
          { label: "一级区域", value: "目标与行动" },
          { label: "当前目标", value: "以已保存选择为准" },
          { label: "市场比较", value: "非变现目标不适用" },
        ]}
      />
      <ReadinessPanel />
    </main>
  );
}

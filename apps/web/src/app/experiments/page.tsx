import { ExperimentPanel } from "@/components/experiment-panel";
import { PageHeader } from "@/components/page-header";

export default function ExperimentsPage() {
  return (
    <main id="main-content" tabIndex={-1} className="page experiments-page">
      <PageHeader
        eyebrow="Goals · Evidence-gated experiment"
        title="先验证能力范围，再记录你亲自完成的求职实验。"
        description="首版只启用初级 C++ 后端与算法应用就业方向。系统负责本地计划、门禁、结果和复盘，不会自动投递、联系、登录平台、签约或交易。"
        context={[
          { label: "一级区域", value: "目标与行动" },
          { label: "首版路径", value: "就业" },
          { label: "外部动作", value: "仅由用户在产品外完成" },
        ]}
      />
      <ExperimentPanel />
    </main>
  );
}

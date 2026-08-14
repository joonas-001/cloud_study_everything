import { LearningDashboard } from "@/components/learning-dashboard";
import { PageHeader } from "@/components/page-header";

export default function LearningPage() {
  return (
    <main id="main-content" tabIndex={-1} className="page learning-page">
      <PageHeader
        eyebrow="Learning workspace · milestone 7D"
        title="一次只推进一个明确任务。"
        description="工作区先呈现当前执行、任务标准和提交反馈，再保留规划、来源与版本依据。证据汇总独立进入六维证据中心。"
        context={[
          { label: "技能包", value: "algorithm@0.2.2" },
          { label: "Runner", value: "本机锁定运行时" },
          { label: "证据", value: "仅限对应能力范围" },
        ]}
      />
      <LearningDashboard skillId="algorithm" skillVersion="0.2.2" />
    </main>
  );
}

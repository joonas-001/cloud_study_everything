import { LearningDashboard } from "@/components/learning-dashboard";
import { PageHeader } from "@/components/page-header";

export default function LearningPage() {
  return (
    <main id="main-content" tabIndex={-1} className="page learning-page">
      <PageHeader
        eyebrow="Learning workspace"
        title="计划可以调整，依据必须留下。"
        description="当前页面验证规划选择、学习活动、隔离代码运行、追加修订、六维证据和固定间隔复习。"
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

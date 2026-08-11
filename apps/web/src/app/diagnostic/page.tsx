import { DiagnosticInterview } from "@/components/diagnostic-interview";
import { PageHeader } from "@/components/page-header";

export default function DiagnosticPage() {
  return (
    <main id="main-content" tabIndex={-1} className="page diagnostic-page">
      <PageHeader
        eyebrow="Learning · Diagnostic preview"
        title="先看清起点，再安排路径。"
        description="这是一条受限的算法技能包诊断预览，用来验证递进提问、分支、修正和审计记录。"
        context={[
          { label: "一级区域", value: "学习" },
          { label: "技能包", value: "algorithm@0.2.2" },
          { label: "外部 AI", value: "默认关闭" },
        ]}
      />
      <DiagnosticInterview />
    </main>
  );
}

import { PageHeader } from "@/components/page-header";
import { SystemSettings } from "@/components/system-settings";

export default function SettingsPage() {
  return (
    <main id="main-content" tabIndex={-1} className="page settings-page">
      <PageHeader
        eyebrow="Settings · Private control"
        title="外发之前，先把边界说清楚。"
        description="邮件和真实 AI 默认不会自动启用。本地密钥保存在 Windows 凭据管理器；私有预发布由主机只读挂载，SQLite 和页面都不会返回原文。"
        context={[
          { label: "访问", value: "单用户私有边界" },
          { label: "凭据", value: "不返回前端" },
          { label: "外部发送", value: "默认关闭" },
        ]}
      />
      <SystemSettings />
    </main>
  );
}

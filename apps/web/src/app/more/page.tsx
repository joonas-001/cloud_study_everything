import Link from "next/link";

import { PageHeader } from "@/components/page-header";

export default function MorePage() {
  return (
    <main id="main-content" tabIndex={-1} className="page more-page">
      <PageHeader
        eyebrow="More"
        title="更多一级能力"
        description="移动底部导航保持五个稳定入口；目标与行动、设置仍是一级产品能力，从这里直接进入。"
        context={[{ label: "移动导航", value: "目标与设置不降级" }]}
      />
      <section className="m7-link-grid m7-link-grid--compact" aria-label="更多一级能力">
        <Link href="/goals">
          <span>目标</span>
          <strong>目标与行动</strong>
          <small>准备度、市场研究和就业实验。</small>
        </Link>
        <Link href="/settings">
          <span>设置</span>
          <strong>设置</strong>
          <small>AI 与隐私、通知、运行与访问边界。</small>
        </Link>
      </section>
    </main>
  );
}

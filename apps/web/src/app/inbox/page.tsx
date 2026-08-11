import Link from "next/link";

import { PageHeader } from "@/components/page-header";

const inboxCategories = [
  { title: "需要确认", description: "规划变化、补充学习单元和其他需要项目所有者决定的事项。" },
  { title: "需要行动", description: "证据到期、延迟复测、实验门禁和需要手动处理的下一步。" },
  { title: "信息变化", description: "来源变化、计划调整和影响范围明确的内容更新。" },
  { title: "系统状态", description: "备份、外部服务和运行环境状态；不在此伪造尚未读取的结果。" },
];

export default function InboxPage() {
  return (
    <main id="main-content" tabIndex={-1} className="page inbox-page">
      <PageHeader
        eyebrow="Inbox · 7B shell"
        title="把需要了解、确认或处理的变化放在同一个地方。"
        description="统一消息聚合将在 7C 接入。当前导航中的未读状态明确显示为“未汇总”，不会用虚构数量代替真实记录。"
        context={[
          { label: "未读状态", value: "尚未汇总", tone: "warning" },
          { label: "现有站内通知", value: "仍在学习工作区" },
          { label: "通知偏好", value: "仍在设置" },
        ]}
        actions={
          <>
            <Link className="primary-button" href="/learning">
              查看现有站内通知
            </Link>
            <Link className="secondary-link" href="/settings">
              管理通知偏好
            </Link>
          </>
        }
      />

      <section className="m7-hub-section" aria-labelledby="inbox-categories-title">
        <div className="m7-section-heading">
          <div>
            <span className="eyebrow">Message taxonomy</span>
            <h2 id="inbox-categories-title">四类事项</h2>
          </div>
          <p>7C 接入时，每条事项必须包含影响范围、时间、下一步、处理结果和审计关联。</p>
        </div>
        <div className="m7-inbox-list">
          {inboxCategories.map((category) => (
            <article key={category.title}>
              <div>
                <h3>{category.title}</h3>
                <p>{category.description}</p>
              </div>
              <span>尚未汇总</span>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}

"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { StatusMessage } from "@/components/status-message";
import type {
  DiagnosticSessionResponse,
  LearningActivityResponse,
  LearningRunResponse,
  NotificationResponse,
  PlanningProposalResponse,
  SourceChangeCandidateResponse,
} from "@/generated/api-schema";
import { PageHeader } from "@/components/page-header";
import {
  getActiveLearningRun,
  getLatestDiagnosticSession,
  getLatestLearningRun,
  getLatestPlanningProposal,
  getNotifications,
  getSourceChangeCandidates,
  messageForError,
} from "@/lib/api";
import { formatNotificationTime, notificationScope, unreadNotificationCount } from "@/lib/inbox";

const SKILL_ID = "algorithm";
const SKILL_VERSION = "0.2.2";

type TodayData = {
  diagnostic: DiagnosticSessionResponse | null;
  proposal: PlanningProposalResponse | null;
  run: LearningRunResponse | null;
  notifications: Array<NotificationResponse>;
  candidates: Array<SourceChangeCandidateResponse>;
};

const completionRuleLabels: Record<LearningActivityResponse["completion_rule"], string> = {
  confirmation: "确认完成来源支持的学习",
  valid_submission: "提交满足结构要求的回答；不据此声称内容正确",
  deterministic_pass: "通过确定性检查或完成可验证纠错",
  runner_pass: "在锁定隔离 Runner 中通过完整确定性测试",
};

const runStatusLabels: Record<LearningRunResponse["status"], string> = {
  active: "学习执行中",
  paused: "学习执行已暂停（不算失败）",
  retention_pending: "等待保持复习",
  completed: "本次流程已完成（不等于掌握）",
  ended: "本次执行已结束",
};

export function TodayDashboard() {
  const [data, setData] = useState<TodayData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([
      getLatestDiagnosticSession(SKILL_ID, SKILL_VERSION),
      getLatestPlanningProposal(SKILL_ID, SKILL_VERSION),
      getActiveLearningRun(SKILL_ID, SKILL_VERSION),
      getLatestLearningRun(SKILL_ID, SKILL_VERSION),
      getNotifications(),
      getSourceChangeCandidates(SKILL_ID, SKILL_VERSION),
    ])
      .then(([diagnostic, proposal, activeRun, latestRun, notifications, candidates]) => {
        if (active) {
          setData({
            diagnostic,
            proposal,
            run: activeRun ?? latestRun,
            notifications,
            candidates,
          });
        }
      })
      .catch((reason: unknown) => {
        if (active) {
          setError(messageForError(reason));
        }
      });
    return () => {
      active = false;
    };
  }, []);

  const summary = useMemo(() => buildTodaySummary(data), [data]);

  return (
    <>
      <PageHeader
        eyebrow="Today · 7C"
        title="今天从最明确的一步开始。"
        description="今日页只聚合当前 API 能确定的任务、复习、阻断和变化；完成状态与能力证据继续分开表达。"
        context={[
          { label: "技能包", value: `${SKILL_ID}@${SKILL_VERSION}` },
          {
            label: "学习状态",
            value: data?.run ? runStatusLabels[data.run.status] : data ? "尚无学习执行" : "读取中",
            tone: data?.run?.status === "active" ? "positive" : "warning",
          },
          {
            label: "未读变化",
            value: data ? `${unreadNotificationCount(data.notifications)} 条` : "读取中",
            tone: data && unreadNotificationCount(data.notifications) > 0 ? "warning" : undefined,
          },
        ]}
        actions={
          <Link className="primary-button" href="/learning">
            进入学习工作区
          </Link>
        }
      />

      {error ? (
        <StatusMessage tone="error" title="今日聚合读取失败">
          {error}
        </StatusMessage>
      ) : null}

      {!data && !error ? (
        <section className="panel loading-panel" role="status" aria-live="polite" aria-busy="true">
          <span className="loading-dot" aria-hidden="true" />
          正在聚合本地任务、复习和变化……
        </section>
      ) : data ? (
        <section className="m7-overview" aria-labelledby="today-overview-title">
          <div className="m7-section-heading">
            <div>
              <span className="eyebrow">Current view</span>
              <h2 id="today-overview-title">今日概览</h2>
            </div>
            <p>从这里查看任务，再到学习工作区执行；证据与变化分别在证据页和收件箱核对。</p>
          </div>
          <div className="m7-overview-grid">
            <article className="m7-overview-card m7-overview-card--primary">
              <span className="m7-card-kicker">当前任务</span>
              <h3>{summary.task.title}</h3>
              <p>{summary.task.description}</p>
              {summary.task.activity ? (
                <dl className="today-task-details">
                  <div><dt>预计耗时</dt><dd>{summary.task.activity.estimated_minutes} 分钟</dd></div>
                  <div><dt>安排原因</dt><dd>{summary.task.activity.reason}</dd></div>
                  <div><dt>完成标准</dt><dd>{completionRuleLabels[summary.task.activity.completion_rule]}</dd></div>
                </dl>
              ) : null}
              <Link href={summary.task.href}>{summary.task.linkLabel}</Link>
            </article>

            <article className="m7-overview-card">
              <span className="m7-card-kicker">到期复习</span>
              <h3>{summary.reviews.title}</h3>
              <p>{summary.reviews.description}</p>
              <Link href="/learning">查看复习记录</Link>
            </article>

            <article className="m7-overview-card">
              <span className="m7-card-kicker">阻断事项</span>
              <h3>{summary.blockers.length === 0 ? "当前未读到明确阻断" : `${summary.blockers.length} 项需要留意`}</h3>
              {summary.blockers.length === 0 ? (
                <p>这只表示当前聚合字段没有明确阻断，不代表能力门禁或整体掌握已经通过。</p>
              ) : (
                <ul className="today-summary-list">
                  {summary.blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}
                </ul>
              )}
              <Link href="/goals">查看目标与行动门禁</Link>
            </article>

            <article className="m7-overview-card">
              <span className="m7-card-kicker">最近变化</span>
              {summary.changes.length === 0 ? (
                <>
                  <h3>目前没有站内变化记录</h3>
                  <p>新规划、来源检查或来源候选出现时会进入收件箱。</p>
                </>
              ) : (
                <ol className="today-change-list">
                  {summary.changes.map((notification) => (
                    <li key={notification.id}>
                      <strong>{notification.title}</strong>
                      <span>{formatNotificationTime(notification.created_at)} · {notificationScope(notification)}</span>
                    </li>
                  ))}
                </ol>
              )}
              <Link href="/inbox">查看全部变化与未读状态</Link>
            </article>
          </div>
        </section>
      ) : null}
    </>
  );
}

function buildTodaySummary(data: TodayData | null) {
  const availableActivities =
    data?.run?.activities.filter((activity) =>
      ["available", "correction_required"].includes(activity.status),
    ) ?? [];
  const taskActivity = availableActivities[0] ?? null;
  const task = taskActivity
    ? {
        title: taskActivity.title,
        description:
          taskActivity.status === "correction_required"
            ? "上次提交需要追加纠错；原尝试与修正都会保留。"
            : taskActivity.prompt,
        activity: taskActivity,
        href: "/learning",
        linkLabel: taskActivity.status === "correction_required" ? "继续纠错" : "执行当前任务",
      }
    : data?.run?.status === "retention_pending"
      ? {
          title: "等待下一次固定间隔复习",
          description: "首轮活动完成后仍需按复习策略验证保持；当前没有可执行活动。",
          activity: null,
          href: "/learning",
          linkLabel: "查看学习执行",
        }
      : !data?.diagnostic
        ? {
            title: "先完成算法技能诊断",
            description: "当前没有可用诊断记录，系统不会在缺少起点证据时伪造今日任务。",
            activity: null,
            href: "/diagnostic",
            linkLabel: "开始诊断",
          }
        : !data.proposal
          ? {
              title: "根据诊断生成规划预览",
              description: "已有诊断记录，但当前精确技能版本尚无规划预览。",
              activity: null,
              href: "/learning",
              linkLabel: "生成规划预览",
            }
          : {
              title: "查看当前学习执行状态",
              description: data.run
                ? runStatusLabels[data.run.status]
                : "已有规划记录，但尚未创建学习执行锁。",
              activity: null,
              href: "/learning",
              linkLabel: "查看学习工作区",
            };

  const dueReviews =
    data?.run?.reviews.filter((review) =>
      review.overdue || review.status === "available" || review.status === "failed",
    ) ?? [];
  const reviews = dueReviews.length > 0
    ? {
        title: `${dueReviews.length} 项复习需要处理`,
        description: dueReviews.some((review) => review.status === "failed")
          ? "包含失败复习；学习执行仍保持 retention_pending，并需要纠错和后续复测。"
          : "已有到期或可执行的固定间隔复习。",
      }
    : {
        title: "当前没有到期复习",
        description: "只依据当前学习执行记录判断；未来已排期复习仍保留在学习工作区。",
      };

  const blockers: Array<string> = [];
  if (availableActivities.some((activity) => activity.status === "correction_required")) {
    blockers.push("存在需要追加纠错的学习活动");
  }
  if (dueReviews.some((review) => review.overdue)) {
    blockers.push("存在已逾期的保持复习");
  }
  if (dueReviews.some((review) => review.status === "failed")) {
    blockers.push("保持复习失败，当前流程不能进入 completed");
  }
  const flags = new Set(data?.run?.dimensions.flatMap((dimension) => dimension.review_flags) ?? []);
  if (flags.has("manual_review_pending")) blockers.push("部分能力范围等待人工复核");
  if (flags.has("source_review_pending")) blockers.push("部分能力范围等待来源复核");
  if (data?.candidates.some((candidate) => candidate.status === "pending")) {
    blockers.push("存在尚未处理的来源变化候选");
  }

  return {
    task,
    reviews,
    blockers,
    changes: data?.notifications.slice(0, 3) ?? [],
  };
}

"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import type {
  DiagnosticSessionResponse,
  NotificationResponse,
  PlanningProposalResponse,
  PlanningUnitResponse,
  SourceChangeCandidateResponse,
  SourceCheckRunResponse,
} from "@/generated/api-schema";
import {
  createPlanningProposal,
  createSourceCheck,
  getLatestDiagnosticSession,
  getLatestPlanningProposal,
  getNotifications,
  getSourceChangeCandidates,
  markNotificationRead,
  messageForError,
  processEmailOutbox,
  resolveSourceChangeCandidate,
  updatePlanningStatus,
  updatePlanningUnit,
} from "@/lib/api";
import { isCurrentDiagnosticProposal } from "@/lib/planning";
import { LearningExecutionPanel } from "@/components/learning-execution-panel";

type EditableUnit = {
  unit: PlanningUnitResponse;
  title: string;
  objective: string;
  reason: string;
  estimatedMinutes: number;
  criteria: string;
};

type LearningDashboardProps = {
  skillId: string;
  skillVersion: string;
};

export function LearningDashboard({
  skillId,
  skillVersion,
}: LearningDashboardProps) {
  const [diagnostic, setDiagnostic] =
    useState<DiagnosticSessionResponse | null>(null);
  const [proposal, setProposal] = useState<PlanningProposalResponse | null>(
    null,
  );
  const [notifications, setNotifications] = useState<
    Array<NotificationResponse>
  >([]);
  const [candidates, setCandidates] = useState<
    Array<SourceChangeCandidateResponse>
  >([]);
  const [sourceRun, setSourceRun] = useState<SourceCheckRunResponse | null>(
    null,
  );
  const [editing, setEditing] = useState<EditableUnit | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([
      getLatestDiagnosticSession(skillId, skillVersion),
      getLatestPlanningProposal(skillId, skillVersion),
      getNotifications(),
      getSourceChangeCandidates(skillId, skillVersion),
      processEmailOutbox().catch(() => null),
    ])
      .then(([nextDiagnostic, nextProposal, nextNotifications, nextCandidates]) => {
        if (!active) {
          return;
        }
        setDiagnostic(nextDiagnostic);
        setProposal(
          isCurrentDiagnosticProposal(nextProposal, nextDiagnostic?.id)
            ? nextProposal
            : null,
        );
        setNotifications(nextNotifications);
        setCandidates(nextCandidates);
      })
      .catch((reason: unknown) => {
        if (active) {
          setError(messageForError(reason));
        }
      })
      .finally(() => {
        if (active) {
          setBusy(false);
        }
      });
    return () => {
      active = false;
    };
  }, [skillId, skillVersion]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (reason: unknown) {
      setError(messageForError(reason));
    } finally {
      setBusy(false);
    }
  }

  function generateProposal() {
    if (!diagnostic) {
      return;
    }
    void run(async () => {
      setProposal(
        await createPlanningProposal({
          diagnostic_session_id: diagnostic.id,
          preview: true,
          provider_id: "local-deterministic",
          model_id: "planner-sim-v1",
        }),
      );
      setNotifications(await getNotifications());
    });
  }

  function checkSources(manual: boolean) {
    void run(async () => {
      setSourceRun(
        await createSourceCheck({
          skill_id: skillId,
          skill_version: skillVersion,
          manual,
        }),
      );
      const [nextNotifications, nextCandidates] = await Promise.all([
        getNotifications(),
        getSourceChangeCandidates(skillId, skillVersion),
      ]);
      setNotifications(nextNotifications);
      setCandidates(nextCandidates);
    });
  }

  function beginEdit(unit: PlanningUnitResponse) {
    setEditing({
      unit,
      title: unit.title,
      objective: unit.objective,
      reason: unit.reason,
      estimatedMinutes: unit.estimated_minutes,
      criteria: unit.completion_criteria.join("\n"),
    });
  }

  function saveUnit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!proposal || !editing) {
      return;
    }
    const completionCriteria = editing.criteria
      .split("\n")
      .map((item) => item.trim())
      .filter(Boolean);
    void run(async () => {
      setProposal(
        await updatePlanningUnit(proposal.id, editing.unit.id, {
          title: editing.title,
          objective: editing.objective,
          reason: editing.reason,
          estimated_minutes: editing.estimatedMinutes,
          completion_criteria: completionCriteria,
        }),
      );
      setEditing(null);
    });
  }

  function setStatus(status: "saved_preview" | "rejected") {
    if (!proposal) {
      return;
    }
    void run(async () => {
      const updated = await updatePlanningStatus(proposal.id, { status });
      setProposal(updated.status === "rejected" ? null : updated);
    });
  }

  function handleCandidate(
    candidateId: string,
    decision: "accepted" | "dismissed",
  ) {
    void run(async () => {
      const updated = await resolveSourceChangeCandidate(candidateId, {
        decision,
      });
      setCandidates((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setNotifications(await getNotifications());
    });
  }

  function readNotification(notificationId: string) {
    void run(async () => {
      const updated = await markNotificationRead(notificationId);
      setNotifications((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
    });
  }

  if (busy && !diagnostic && !proposal) {
    return (
      <section className="panel loading-panel" aria-live="polite">
        <span className="loading-dot" aria-hidden="true" />
        正在读取本地规划、来源和通知……
      </section>
    );
  }

  return (
    <div className="learning-layout">
      <section className="learning-main">
        {error ? (
          <div className="error-banner" role="alert">
            <strong>暂时无法完成操作</strong>
            <span>{error}</span>
          </div>
        ) : null}

        <section className="panel learning-control">
          <div>
            <span className="preview-badge">草稿规划预览 · 本地模拟</span>
            <h2>今天从可信记录开始</h2>
            <p>
              开始学习时会检查当前预览引用的受监测来源。远程失败不会阻止学习，但会明确标记风险。
            </p>
          </div>
          <div className="learning-control-actions">
            <button
              className="primary-button"
              type="button"
              disabled={busy}
              onClick={() => checkSources(false)}
            >
              开始今日学习
            </button>
            <button
              className="text-button"
              type="button"
              disabled={busy}
              onClick={() => checkSources(true)}
            >
              手动重新检查来源
            </button>
          </div>
        </section>

        {sourceRun ? (
          <section
            className={`source-run ${sourceRun.failed_count ? "has-warning" : ""}`}
            aria-live="polite"
          >
            <div>
              <strong>
                {sourceRun.reused ? "已使用今日检查记录" : "来源检查已完成"}
              </strong>
              <span>
                检查 {sourceRun.checked_count} 项 · 变化 {sourceRun.changed_count} 项 ·
                待复核{" "}
                {
                  sourceRun.results.filter(
                    (item) =>
                      item.status === "manual" ||
                      item.status === "indeterminate",
                  ).length
                }{" "}
                项 · 失败 {sourceRun.failed_count} 项
              </span>
            </div>
            {sourceRun.results
              .filter(
                (item) =>
                  item.status === "failed" ||
                  item.status === "manual" ||
                  item.status === "indeterminate",
              )
              .map((item) => (
                <p key={item.source_id}>
                  {item.source_title}：{item.error_message}。最近成功：
                  {item.last_success_at ?? "尚无成功记录"}
                </p>
              ))}
          </section>
        ) : null}

        <LearningExecutionPanel
          key={`${proposal?.id ?? "no-plan"}:${proposal?.updated_at ?? "none"}`}
          skillId={skillId}
          skillVersion={skillVersion}
        />

        {!diagnostic ? (
          <section className="panel empty-state learning-empty">
            <span className="step-mark">01</span>
            <h2>先完成诊断预览</h2>
            <p>规划必须锁定一份已结束的诊断记录，不能跳过真实起点。</p>
            <Link className="primary-button" href="/diagnostic">
              前往算法诊断
            </Link>
          </section>
        ) : diagnostic.status === "active" ? (
          <section className="panel empty-state learning-empty">
            <span className="step-mark">02</span>
            <h2>诊断仍在进行</h2>
            <p>结束当前诊断后，才能生成锁定该记录的本地规划预览。</p>
            <Link className="primary-button" href="/diagnostic">
              继续诊断
            </Link>
          </section>
        ) : null}

        {diagnostic?.status === "ended" && !proposal ? (
          <section className="panel empty-state learning-empty">
            <span className="step-mark">03</span>
            <h2>生成来源支持的规划预览</h2>
            <p>
              本地模拟器会生成可复现的共同主干入口安排。它无法判断自由文本答案是否正确，不会产生掌握结论。
            </p>
            <button
              className="primary-button"
              type="button"
              disabled={busy}
              onClick={generateProposal}
            >
              生成本地规划预览
            </button>
          </section>
        ) : null}

        {proposal ? (
          <section className="plan-preview">
            <header className="plan-header">
              <div>
                <span className="eyebrow">
                  {proposal.provider_id} · {proposal.model_id}
                </span>
                <h2>{proposal.title}</h2>
                <p>{proposal.rationale}</p>
              </div>
              <span className="status">
                {proposal.status === "draft"
                  ? "可修改"
                  : proposal.status === "saved_preview"
                    ? "预览已保存"
                    : "已否决"}
              </span>
            </header>

            <aside className="plan-limitations">
              <strong>当前限制</strong>
              <ul>
                {proposal.limitations.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </aside>

            <ol className="plan-units">
              {proposal.units.map((unit) => (
                <li className="plan-unit" key={unit.id}>
                  <div className="plan-sequence">
                    {String(unit.sequence).padStart(2, "0")}
                  </div>
                  <div className="plan-unit-content">
                    <header>
                      <div>
                        <span>{unit.estimated_minutes} 分钟</span>
                        <h3>{unit.title}</h3>
                      </div>
                      {proposal.status === "draft" ? (
                        <button
                          className="text-button"
                          type="button"
                          disabled={busy}
                          onClick={() => beginEdit(unit)}
                        >
                          修改安排
                        </button>
                      ) : null}
                    </header>
                    <p>{unit.objective}</p>
                    <dl>
                      <div>
                        <dt>为什么安排</dt>
                        <dd>{unit.reason}</dd>
                      </div>
                      <div>
                        <dt>完成标准</dt>
                        <dd>
                          <ul>
                            {unit.completion_criteria.map((criterion) => (
                              <li key={criterion}>{criterion}</li>
                            ))}
                          </ul>
                        </dd>
                      </div>
                    </dl>
                    <div className="source-links">
                      <strong>来源</strong>
                      {unit.sources.map((source) => (
                        <a
                          href={source.url}
                          key={source.id}
                          rel="noreferrer"
                          target="_blank"
                        >
                          {source.publisher} · {source.title}
                        </a>
                      ))}
                    </div>
                  </div>
                </li>
              ))}
            </ol>

            {proposal.status === "draft" ? (
              <div className="plan-actions">
                <button
                  className="primary-button"
                  type="button"
                  disabled={busy}
                  onClick={() => setStatus("saved_preview")}
                >
                  保存这份预览
                </button>
                <button
                  className="end-link"
                  type="button"
                  disabled={busy}
                  onClick={() => setStatus("rejected")}
                >
                  否决这份预览
                </button>
              </div>
            ) : null}
          </section>
        ) : null}

        {editing ? (
          <form className="panel plan-editor" onSubmit={saveUnit}>
            <div>
              <span className="eyebrow">修改规划单元</span>
              <h2>{editing.unit.template_unit_id}</h2>
            </div>
            <label>
              标题
              <input
                value={editing.title}
                disabled={busy}
                onChange={(event) =>
                  setEditing({ ...editing, title: event.target.value })
                }
              />
            </label>
            <label>
              学习目标
              <textarea
                value={editing.objective}
                disabled={busy}
                onChange={(event) =>
                  setEditing({ ...editing, objective: event.target.value })
                }
              />
            </label>
            <label>
              安排原因
              <textarea
                value={editing.reason}
                disabled={busy}
                onChange={(event) =>
                  setEditing({ ...editing, reason: event.target.value })
                }
              />
            </label>
            <label>
              预计分钟
              <input
                type="number"
                min={15}
                max={180}
                value={editing.estimatedMinutes}
                disabled={busy}
                onChange={(event) =>
                  setEditing({
                    ...editing,
                    estimatedMinutes: Number(event.target.value),
                  })
                }
              />
            </label>
            <label>
              完成标准（每行一项）
              <textarea
                value={editing.criteria}
                disabled={busy}
                onChange={(event) =>
                  setEditing({ ...editing, criteria: event.target.value })
                }
              />
            </label>
            <div className="answer-actions">
              <button className="primary-button" type="submit" disabled={busy}>
                保存修改
              </button>
              <button
                className="text-button"
                type="button"
                disabled={busy}
                onClick={() => setEditing(null)}
              >
                取消
              </button>
            </div>
          </form>
        ) : null}
      </section>

      <aside className="learning-sidebar">
        <section className="panel notification-center">
          <header>
            <div>
              <span className="eyebrow">Notification center</span>
              <h2>站内通知</h2>
            </div>
            <Link href="/settings">通知设置</Link>
          </header>
          {notifications.length === 0 ? (
            <p className="muted">目前没有通知。</p>
          ) : (
            <ol>
              {notifications.map((item) => (
                <li className={item.read_at ? "is-read" : ""} key={item.id}>
                  <span className={`severity ${item.severity}`}>
                    {item.severity}
                  </span>
                  <strong>{item.title}</strong>
                  <p>{item.message}</p>
                  {item.email_status ? (
                    <small>邮件：{item.email_status}</small>
                  ) : null}
                  {!item.read_at ? (
                    <button
                      className="text-button"
                      type="button"
                      disabled={busy}
                      onClick={() => readNotification(item.id)}
                    >
                      标记已读
                    </button>
                  ) : null}
                </li>
              ))}
            </ol>
          )}
        </section>

        {candidates.some((item) => item.status === "pending") ? (
          <section className="panel candidate-list">
            <span className="eyebrow">Review required</span>
            <h2>来源变化候选</h2>
            {candidates
              .filter((item) => item.status === "pending")
              .map((candidate) => (
                <article key={candidate.id}>
                  <strong>{candidate.source_title}</strong>
                  <p>{candidate.summary}</p>
                  <div className="answer-actions">
                    <button
                      className="text-button"
                      type="button"
                      disabled={busy}
                      onClick={() =>
                        handleCandidate(candidate.id, "accepted")
                      }
                    >
                      接受候选
                    </button>
                    <button
                      className="text-button"
                      type="button"
                      disabled={busy}
                      onClick={() =>
                        handleCandidate(candidate.id, "dismissed")
                      }
                    >
                      忽略
                    </button>
                  </div>
                </article>
              ))}
          </section>
        ) : null}
      </aside>
    </div>
  );
}

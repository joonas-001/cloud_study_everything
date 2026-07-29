"use client";

import { useEffect, useMemo, useState } from "react";

import type {
  LearningActivityResponse,
  LearningEvidenceResponse,
  LearningRunResponse,
  PlanningOptionResponse,
  TodayLearningResponse,
} from "@/generated/api-schema";
import {
  correctLearningActivityAttempt,
  createLearningRun,
  endLearningRun,
  generateTodayLearning,
  getLearningEvidence,
  getLearningPlanOptions,
  getLatestLearningRun,
  messageForError,
  selfReviewActivityAttempt,
  submitLearningActivityAttempt,
} from "@/lib/api";

type LearningExecutionPanelProps = {
  skillId: string;
  skillVersion: string;
};

const dimensionLabels: Record<string, string> = {
  understanding: "理解",
  operation: "操作",
  transfer: "迁移",
  artifact: "作品",
  retention: "保持",
  correction: "纠错",
};

const evidenceLabels: Record<string, string> = {
  none: "尚无证据",
  limited: "有限证据",
  supported: "确定性支持",
};

const flagLabels: Record<string, string> = {
  manual_review_pending: "待未来独立复核",
  retention_due: "待延迟复习",
  source_review_pending: "来源待复核",
};

function selfReviewRubric(activity: LearningActivityResponse): string | null {
  if (activity.template_activity_id === "checkpoint-explanation") {
    return "explanation-self-review";
  }
  if (activity.template_activity_id === "checkpoint-transfer") {
    return "transfer-self-review";
  }
  if (activity.template_activity_id === "checkpoint-project") {
    return "project-self-review";
  }
  return null;
}

export function LearningExecutionPanel({
  skillId,
  skillVersion,
}: LearningExecutionPanelProps) {
  const [plans, setPlans] = useState<Array<PlanningOptionResponse>>([]);
  const [selectedPlanId, setSelectedPlanId] = useState("");
  const [confirmHistorical, setConfirmHistorical] = useState(false);
  const [confirmReuse, setConfirmReuse] = useState(false);
  const [run, setRun] = useState<LearningRunResponse | null>(null);
  const [today, setToday] = useState<TodayLearningResponse | null>(null);
  const [evidence, setEvidence] = useState<LearningEvidenceResponse | null>(
    null,
  );
  const [availableMinutes, setAvailableMinutes] = useState(120);
  const [selectedActivityId, setSelectedActivityId] = useState("");
  const [submission, setSubmission] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([
      getLearningPlanOptions(skillId, skillVersion),
      getLatestLearningRun(skillId, skillVersion),
    ])
      .then(([nextPlans, nextRun]) => {
        if (!active) {
          return;
        }
        setPlans(nextPlans);
        setSelectedPlanId(
          nextRun &&
            ["active", "retention_pending"].includes(nextRun.status)
            ? nextRun.planning_proposal_id
            : nextPlans[0]?.id ?? "",
        );
        setRun(nextRun);
        if (nextRun) {
          return getLearningEvidence(nextRun.id).then((nextEvidence) => {
            if (active) {
              setEvidence(nextEvidence);
            }
          });
        }
        return undefined;
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

  const selectedPlan = plans.find((item) => item.id === selectedPlanId) ?? null;
  const availableActivities = useMemo(
    () =>
      today?.tasks ??
      run?.activities.filter((item) =>
        ["available", "correction_required"].includes(item.status),
      ) ??
      [],
    [run, today],
  );
  const selectedActivity =
    availableActivities.find((item) => item.id === selectedActivityId) ??
    availableActivities[0] ??
    null;

  async function execute(action: () => Promise<void>) {
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

  function createOrReuseRun() {
    if (!selectedPlan) {
      return;
    }
    const reusable =
      run &&
      ["completed", "ended"].includes(run.status) &&
      run.planning_proposal_id === selectedPlan.id
        ? run
        : null;
    void execute(async () => {
      const created = await createLearningRun({
        planning_proposal_id: selectedPlan.id,
        preview: true,
        code_execution: false,
        external_ai: false,
        confirm_historical_plan: !selectedPlan.is_historical || confirmHistorical,
        reuse_from_run_id: reusable?.id ?? null,
        confirm_reuse: reusable ? confirmReuse : false,
      });
      setRun(created);
      setToday(null);
      setEvidence(await getLearningEvidence(created.id));
      setConfirmReuse(false);
    });
  }

  function generateToday() {
    if (!run) {
      return;
    }
    void execute(async () => {
      const nextToday = await generateTodayLearning(run.id, {
        available_minutes: availableMinutes,
      });
      setToday(nextToday);
      setSelectedActivityId(nextToday.tasks[0]?.id ?? "");
      setSubmission({});
    });
  }

  function submitActivity(markUncertain = false) {
    if (!run || !selectedActivity) {
      return;
    }
    void execute(async () => {
      const latestAttempt =
        selectedActivity.attempts[selectedActivity.attempts.length - 1];
      const payload = {
        submission,
        mark_uncertain: markUncertain,
      };
      const result =
        selectedActivity.status === "correction_required" && latestAttempt
          ? await correctLearningActivityAttempt(
              selectedActivity.id,
              latestAttempt.id,
              payload,
            )
          : await submitLearningActivityAttempt(selectedActivity.id, payload);
      setRun(result.run);
      setToday(null);
      setSubmission({});
      setEvidence(await getLearningEvidence(result.run.id));
    });
  }

  function reviewAttempt(
    activity: LearningActivityResponse,
    result: "not_yet" | "uncertain" | "meets",
  ) {
    const rubricId = selfReviewRubric(activity);
    const attempt = activity.attempts[activity.attempts.length - 1];
    if (!run || !rubricId || !attempt) {
      return;
    }
    void execute(async () => {
      const reviewed = await selfReviewActivityAttempt(attempt.id, {
        rubric_id: rubricId,
        result,
      });
      setRun(reviewed.run);
      setToday(null);
      setSelectedActivityId(
        reviewed.activity.status === "correction_required"
          ? reviewed.activity.id
          : "",
      );
      setSubmission({});
      setEvidence(await getLearningEvidence(reviewed.run.id));
    });
  }

  function finishRun() {
    if (!run) {
      return;
    }
    void execute(async () => {
      setRun(await endLearningRun(run.id));
      setToday(null);
    });
  }

  return (
    <section className="execution-panel" aria-live="polite">
      <header className="execution-header">
        <div>
          <span className="preview-badge">
            algorithm@{skillVersion} · 4A 受限执行
          </span>
          <h2>学习执行与证据</h2>
          <p>
            所有提交只保存在本地。代码文本不执行，完成活动不等于内容正确或已经掌握。
          </p>
        </div>
        <div className="execution-guardrails">
          <span>代码执行：关闭</span>
          <span>外部 AI：关闭</span>
          <span>文件上传：关闭</span>
        </div>
      </header>

      {error ? (
        <div className="error-banner" role="alert">
          <strong>学习执行暂时无法继续</strong>
          <span>{error}</span>
        </div>
      ) : null}

      {!run || ["completed", "ended"].includes(run.status) ? (
        <section className="execution-start">
          <div>
            <span className="eyebrow">不可变规划锁</span>
            <h3>选择一份已保存规划</h3>
            {plans.length === 0 ? (
              <p className="muted">保存规划预览后，才能创建学习执行。</p>
            ) : (
              <div className="plan-option-list">
                {plans.map((plan) => (
                  <label key={plan.id}>
                    <input
                      type="radio"
                      name="planning-option"
                      checked={selectedPlanId === plan.id}
                      disabled={busy}
                      onChange={() => {
                        setSelectedPlanId(plan.id);
                        setConfirmHistorical(false);
                        setConfirmReuse(false);
                      }}
                    />
                    <span>
                      <strong>{plan.title}</strong>
                      <small>
                        保存于 {new Date(plan.saved_at).toLocaleString("zh-CN")}
                      </small>
                      {plan.is_historical ? (
                        <em>早于最新诊断或规划</em>
                      ) : null}
                      {plan.source_review_pending ? <em>存在来源待办</em> : null}
                    </span>
                  </label>
                ))}
              </div>
            )}
          </div>
          {selectedPlan?.is_historical ? (
            <label className="confirmation-row">
              <input
                type="checkbox"
                checked={confirmHistorical}
                disabled={busy}
                onChange={(event) => setConfirmHistorical(event.target.checked)}
              />
              我理解这份规划早于最新诊断或规划，仍明确选择它。
            </label>
          ) : null}
          {run &&
          ["completed", "ended"].includes(run.status) &&
          run.planning_proposal_id === selectedPlanId ? (
            <label className="confirmation-row">
              <input
                type="checkbox"
                checked={confirmReuse}
                disabled={busy}
                onChange={(event) => setConfirmReuse(event.target.checked)}
              />
              我确认复用同一不可变规划创建全新的执行记录；旧历史不会被覆盖。
            </label>
          ) : null}
          <button
            className="primary-button"
            type="button"
            disabled={
              busy ||
              !selectedPlan ||
              (selectedPlan.is_historical && !confirmHistorical) ||
              Boolean(
                run &&
                  ["completed", "ended"].includes(run.status) &&
                  run.planning_proposal_id === selectedPlanId &&
                  !confirmReuse,
              )
            }
            onClick={createOrReuseRun}
          >
            {run &&
            ["completed", "ended"].includes(run.status) &&
            run.planning_proposal_id === selectedPlanId
              ? "创建新的独立执行"
              : "创建学习执行锁"}
          </button>
        </section>
      ) : null}

      {run ? (
        <>
          <section className="run-summary">
            <div>
              <span className={`run-status ${run.status}`}>{run.status}</span>
              <strong>技能包 {run.skill_version}</strong>
              <small>锁摘要 {run.lock_sha256.slice(0, 16)}…</small>
            </div>
            <p>
              {run.status === "retention_pending"
                ? "首轮活动已完成，必须通过固定第 1、2、4、7、15 天复习后才能完成本次流程。"
                : run.status === "completed"
                  ? "本次流程已完成；这不是掌握结论。"
                  : run.status === "ended"
                    ? "本次执行已明确结束且不可恢复，历史仍完整保留。"
                    : "按真实完成情况推进；未完成任务不会记作能力失败。"}
            </p>
          </section>

          {!["completed", "ended"].includes(run.status) ? (
            <section className="today-control">
              <label>
                今日可用时间
                <span>
                  <input
                    type="number"
                    min={15}
                    max={480}
                    value={availableMinutes}
                    disabled={busy}
                    onChange={(event) =>
                      setAvailableMinutes(Number(event.target.value))
                    }
                  />
                  分钟
                </span>
              </label>
              <button
                className="primary-button"
                type="button"
                disabled={busy}
                onClick={generateToday}
              >
                生成今日任务
              </button>
              {today ? (
                <p>
                  {today.reason} 当前选择 {today.tasks.length} 项，预计{" "}
                  {today.estimated_minutes} 分钟。
                </p>
              ) : null}
            </section>
          ) : null}

          {availableActivities.length > 0 &&
          !["completed", "ended"].includes(run.status) ? (
            <section className="activity-workspace">
              <nav aria-label="今日学习活动">
                {availableActivities.map((activity) => (
                  <button
                    type="button"
                    className={
                      selectedActivity?.id === activity.id ? "is-current" : ""
                    }
                    key={activity.id}
                    disabled={busy}
                    onClick={() => {
                      setSelectedActivityId(activity.id);
                      setSubmission({});
                    }}
                  >
                    <span>{activity.type}</span>
                    <strong>{activity.title}</strong>
                    <small>
                      {activity.estimated_minutes} 分钟
                      {activity.overdue ? " · 已逾期（不算失败）" : ""}
                    </small>
                  </button>
                ))}
              </nav>
              {selectedActivity ? (
                <article className="activity-card">
                  <span className="eyebrow">{selectedActivity.type}</span>
                  <h3>{selectedActivity.title}</h3>
                  <p>{selectedActivity.prompt}</p>
                  <aside>
                    <strong>为什么安排</strong>
                    {selectedActivity.reason}
                  </aside>
                  {selectedActivity.type === "code_text" ||
                  selectedActivity.type === "project_evidence" ? (
                    <div className="code-warning">
                      代码仅作为不可信文本保存，不会编译、运行或发送给外部 AI。
                    </div>
                  ) : null}
                  <div className="submission-fields">
                    {selectedActivity.submission_fields.map((field) =>
                      field.kind === "choice" ? (
                        <label key={field.id}>
                          {field.label}
                          <select
                            value={submission[field.id] ?? ""}
                            disabled={busy}
                            onChange={(event) =>
                              setSubmission({
                                ...submission,
                                [field.id]: event.target.value,
                              })
                            }
                          >
                            <option value="">请选择</option>
                            {(field.options ?? []).map((option) => (
                              <option key={option} value={option}>
                                {option}
                              </option>
                            ))}
                          </select>
                        </label>
                      ) : field.kind === "confirmation" ? (
                        <label className="confirmation-row" key={field.id}>
                          <input
                            type="checkbox"
                            checked={submission[field.id] === "true"}
                            disabled={busy}
                            onChange={(event) =>
                              setSubmission({
                                ...submission,
                                [field.id]: event.target.checked ? "true" : "",
                              })
                            }
                          />
                          {field.label}
                        </label>
                      ) : (
                        <label key={field.id}>
                          {field.label}
                          <textarea
                            className={field.kind === "code" ? "code-input" : ""}
                            value={submission[field.id] ?? ""}
                            minLength={field.min_length}
                            maxLength={field.max_length}
                            disabled={busy}
                            onChange={(event) =>
                              setSubmission({
                                ...submission,
                                [field.id]: event.target.value,
                              })
                            }
                          />
                        </label>
                      ),
                    )}
                  </div>
                  <div className="answer-actions">
                    <button
                      className="primary-button"
                      type="button"
                      disabled={busy}
                      onClick={() => submitActivity(false)}
                    >
                      {selectedActivity.status === "correction_required"
                        ? "提交追加修正"
                        : "提交并继续"}
                    </button>
                    {selectedActivity.completion_rule ===
                    "deterministic_pass" ? (
                      <button
                        className="text-button"
                        type="button"
                        disabled={busy}
                        onClick={() => submitActivity(true)}
                      >
                        我不确定
                      </button>
                    ) : null}
                  </div>
                </article>
              ) : null}
            </section>
          ) : null}

          <section className="mastery-grid" aria-label="六维证据">
            <header>
              <div>
                <span className="eyebrow">Evidence dimensions</span>
                <h3>六维证据，不是掌握百分比</h3>
              </div>
              <button
                className="text-button"
                type="button"
                disabled={busy}
                onClick={() => {
                  if (run) {
                    void execute(async () => {
                      setEvidence(await getLearningEvidence(run.id));
                    });
                  }
                }}
              >
                刷新证据
              </button>
            </header>
            <div>
              {(evidence?.dimensions ?? run.dimensions).map((dimension) => (
                <article key={dimension.dimension}>
                  <span>{dimensionLabels[dimension.dimension]}</span>
                  <strong>{evidenceLabels[dimension.evidence_level]}</strong>
                  <small>{dimension.evidence_count} 条当前证据</small>
                  <ul>
                    {dimension.review_flags.map((flag) => (
                      <li key={flag}>{flagLabels[flag]}</li>
                    ))}
                  </ul>
                </article>
              ))}
            </div>
            <p>
              4A 不会生成 scope_criteria_met、verified、不受限 retained
              或“已经掌握”状态。
            </p>
          </section>

          {!["completed", "ended"].includes(run.status) ? (
            <section className="self-review-list">
            <span className="eyebrow">Self review</span>
            <h3>结构有效提交的自评待办</h3>
            {run.activities
              .filter((activity) => {
                const rubric = selfReviewRubric(activity);
                const latest =
                  activity.attempts[activity.attempts.length - 1];
                return (
                  rubric &&
                  latest &&
                  !latest.evaluations.some(
                    (evaluation) => evaluation.method === "self_review",
                  )
                );
              })
              .map((activity) => (
                <article key={activity.id}>
                  <div>
                    <strong>{activity.title}</strong>
                    <p>
                      请选择依据量表的自评。即使选择“自评满足”，也只形成有限证据。
                    </p>
                  </div>
                  <div className="answer-actions">
                    <button
                      type="button"
                      className="text-button"
                      disabled={busy}
                      onClick={() => reviewAttempt(activity, "meets")}
                    >
                      自评满足
                    </button>
                    <button
                      type="button"
                      className="text-button"
                      disabled={busy}
                      onClick={() => reviewAttempt(activity, "uncertain")}
                    >
                      不确定
                    </button>
                    <button
                      type="button"
                      className="text-button"
                      disabled={busy}
                      onClick={() => reviewAttempt(activity, "not_yet")}
                    >
                      需要修订
                    </button>
                  </div>
                </article>
              ))}
            </section>
          ) : null}

          {run.reviews.length > 0 ? (
            <section className="review-timeline">
              <span className="eyebrow">Fixed expanding review</span>
              <h3>第 1、2、4、7、15 天主动提取</h3>
              <ol>
                {run.reviews.map((review) => (
                  <li key={review.id}>
                    <strong>
                      第 {review.checkpoint_index} 个检查点 · 第{" "}
                      {review.attempt_number} 次
                    </strong>
                    <span>
                      {new Date(review.due_at).toLocaleString("zh-CN")} ·{" "}
                      {review.status}
                      {review.overdue ? " · 逾期不算失败" : ""}
                    </span>
                  </li>
                ))}
              </ol>
            </section>
          ) : null}

          {!["completed", "ended"].includes(run.status) ? (
            <button
              className="end-link"
              type="button"
              disabled={busy}
              onClick={finishRun}
            >
              明确结束本次学习执行
            </button>
          ) : null}
        </>
      ) : null}
    </section>
  );
}

"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { StatusMessage } from "@/components/status-message";
import type {
  BranchGateEvaluationResponse,
  LearningIndependentReviewResponse,
  LearningActivityResponse,
  LearningRunResponse,
  PlanningOptionResponse,
  RunnerAvailabilityResponse,
  RunnerInvocationResponse,
  StageCheckpointResponse,
  TodayLearningResponse,
} from "@/generated/api-schema";
import {
  correctLearningActivityAttempt,
  createLearningIndependentReview,
  createLearningRun,
  endLearningRun,
  executeRunnerAttempt,
  generateTodayLearning,
  getLearningBranchGates,
  getLearningPlanOptions,
  getLearningStageCheckpoints,
  getLatestLearningRun,
  getRunnerAvailability,
  messageForError,
  pauseLearningRun,
  resumeLearningRun,
  selfReviewActivityAttempt,
  submitLearningActivityAttempt,
} from "@/lib/api";

type LearningExecutionPanelProps = {
  skillId: string;
  skillVersion: string;
};

const runnerReasonLabels: Record<string, string> = {
  docker_unavailable: "尚未安装 Docker Desktop",
  docker_daemon_unavailable: "Docker Desktop 服务未就绪",
  runner_disk_budget_unavailable: "D 盘剩余空间低于安全门槛",
  runner_disk_budget_exceeded: "Runner 数据已超过 6 GB 预算",
};

const dailyPriorityLabels: Record<string, string> = {
  due_retention: "到期保持",
  failed_correction: "失败纠错",
  blocking_prerequisite: "阻断前置",
  new_content: "新内容",
};

const checkpointStatusLabels: Record<string, string> = {
  not_started: "尚未开始",
  in_progress: "初轮学习中",
  initial_learning_completed: "初轮学习已完成",
};

function requirementLabel(requirement: Record<string, unknown>): string {
  const title = String(requirement.title ?? requirement.capability_id ?? "未知能力");
  const dimension = String(requirement.dimension ?? "未知维度");
  const required = requirement.required_level
    ? `需 ${String(requirement.required_level)}`
    : "需真人复核";
  const actual = requirement.actual_level
    ? `，现有 ${String(requirement.actual_level)}`
    : "";
  return `${title} · ${dimension} · ${required}${actual}`;
}

function localDateTimeValue(date = new Date()): string {
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

function runnerTests(
  invocation: RunnerInvocationResponse,
): Array<Record<string, unknown>> {
  const tests = invocation.result?.tests;
  if (!Array.isArray(tests)) {
    return [];
  }
  return tests.filter(
    (item): item is Record<string, unknown> =>
      typeof item === "object" && item !== null,
  );
}

function selfReviewRubric(activity: LearningActivityResponse): string | null {
  if (activity.template_activity_id === "checkpoint-explanation") {
    return "explanation-self-review";
  }
  if (activity.type === "explanation") {
    return "understanding-rubric";
  }
  if (activity.template_activity_id === "checkpoint-transfer") {
    return "transfer-self-review";
  }
  if (activity.type === "transfer") {
    return "transfer-rubric";
  }
  if (activity.template_activity_id === "checkpoint-project") {
    return "project-self-review";
  }
  if (activity.type === "project_evidence") {
    return "artifact-rubric";
  }
  if (activity.type === "correction") {
    return "correction-rubric";
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
  const [confirmCodeExecution, setConfirmCodeExecution] = useState(false);
  const [run, setRun] = useState<LearningRunResponse | null>(null);
  const [today, setToday] = useState<TodayLearningResponse | null>(null);
  const [runnerAvailability, setRunnerAvailability] =
    useState<RunnerAvailabilityResponse | null>(null);
  const [availableMinutes, setAvailableMinutes] = useState(120);
  const [allowOvertime, setAllowOvertime] = useState(false);
  const [overtimeReason, setOvertimeReason] = useState("");
  const [pauseReason, setPauseReason] = useState("");
  const [stageCheckpoints, setStageCheckpoints] = useState<
    Array<StageCheckpointResponse>
  >([]);
  const [executionMetadataRunId, setExecutionMetadataRunId] = useState("");
  const [branchGates, setBranchGates] =
    useState<BranchGateEvaluationResponse | null>(null);
  const [independentReviews, setIndependentReviews] = useState<
    Array<LearningIndependentReviewResponse>
  >([]);
  const [reviewerRelationship, setReviewerRelationship] = useState("");
  const [reviewDimension, setReviewDimension] = useState<
    "understanding" | "operation" | "transfer" | "artifact" | "retention" | "correction"
  >("understanding");
  const [reviewConclusion, setReviewConclusion] = useState<
    "meets" | "needs_work" | "uncertain"
  >("meets");
  const [reviewedAt, setReviewedAt] = useState(localDateTimeValue());
  const [selectedActivityId, setSelectedActivityId] = useState("");
  const [submission, setSubmission] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([
      getLearningPlanOptions(skillId, skillVersion),
      getLatestLearningRun(skillId, skillVersion),
      getRunnerAvailability(),
    ])
      .then(([nextPlans, nextRun, nextRunnerAvailability]) => {
        if (!active) {
          return;
        }
        setPlans(nextPlans);
        setSelectedPlanId(
          nextRun &&
            ["active", "paused", "retention_pending"].includes(nextRun.status)
            ? nextRun.planning_proposal_id
            : nextPlans[0]?.id ?? "",
        );
        setRun(nextRun);
        setRunnerAvailability(nextRunnerAvailability);
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

  useEffect(() => {
    let active = true;
    if (!run) {
      return () => {
        active = false;
      };
    }
    getLearningStageCheckpoints(run.id)
      .then(async (checkpoints) => {
        const gates =
          checkpoints.length > 0 ? await getLearningBranchGates(run.id) : null;
        if (!active) {
          return;
        }
        setExecutionMetadataRunId(run.id);
        setStageCheckpoints(checkpoints);
        setBranchGates(gates);
      })
      .catch((reason: unknown) => {
        if (active) {
          setError(messageForError(reason));
        }
      });
    return () => {
      active = false;
    };
  }, [run]);

  const selectedPlan = plans.find((item) => item.id === selectedPlanId) ?? null;
  const availableActivities = useMemo(
    () =>
      run?.status === "paused"
        ? []
        : today?.tasks ??
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
  const latestAttempt =
    selectedActivity?.attempts[selectedActivity.attempts.length - 1] ?? null;

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
        code_execution: confirmCodeExecution,
        external_ai: false,
        confirm_historical_plan: !selectedPlan.is_historical || confirmHistorical,
        reuse_from_run_id: reusable?.id ?? null,
        confirm_reuse: reusable ? confirmReuse : false,
      });
      setRun(created);
      setToday(null);
      setConfirmReuse(false);
    });
  }

  function runLatestAttempt() {
    if (!run || !latestAttempt) {
      return;
    }
    void execute(async () => {
      const result = await executeRunnerAttempt(latestAttempt.id);
      setRun(result.run);
      setToday(null);
    });
  }

  function generateToday() {
    if (!run) {
      return;
    }
    void execute(async () => {
      const nextToday = await generateTodayLearning(run.id, {
        available_minutes: availableMinutes,
        allow_overtime: availableMinutes > 120 && allowOvertime,
        overtime_reason:
          availableMinutes > 120 && allowOvertime ? overtimeReason : null,
      });
      setToday(nextToday);
      setSelectedActivityId(nextToday.tasks[0]?.id ?? "");
      setSubmission({});
    });
  }

  function pauseRun() {
    if (!run) {
      return;
    }
    void execute(async () => {
      setRun(await pauseLearningRun(run.id, { reason: pauseReason }));
      setToday(null);
      setPauseReason("");
    });
  }

  function resumeRun() {
    if (!run) {
      return;
    }
    void execute(async () => {
      setRun(await resumeLearningRun(run.id));
      setToday(null);
    });
  }

  function recordIndependentReview() {
    if (!run || !selectedActivity || selectedActivity.capability_ids.length === 0) {
      return;
    }
    void execute(async () => {
      const review = await createLearningIndependentReview(run.id, {
        activity_id: selectedActivity.id,
        capability_ids: selectedActivity.capability_ids,
        dimension: reviewDimension,
        reviewer_relationship: reviewerRelationship,
        rubric_id: `${reviewDimension}-rubric`,
        rubric_version: "1.0.0",
        conclusion: reviewConclusion,
        reviewed_at: new Date(reviewedAt).toISOString(),
      });
      setIndependentReviews((items) => [...items, review]);
      setReviewerRelationship("");
      setReviewedAt(localDateTimeValue());
      setBranchGates(await getLearningBranchGates(run.id));
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
            algorithm@{skillVersion} · 共同主干学习执行
          </span>
          <h2>学习执行与证据</h2>
          <p>
            代码仅在锁定镜像的本地隔离容器中按确定性测试运行。通过只证明对应任务范围，不等于整体掌握。
          </p>
        </div>
        <div className="execution-header__aside">
          <div className="execution-guardrails">
            <span>
              Runner：
              {runnerAvailability?.available
                ? "本地可用"
                : runnerReasonLabels[runnerAvailability?.reason_code ?? ""] ??
                  "不可用"}
            </span>
            <span>外部 AI：关闭</span>
            <span>文件上传：关闭</span>
          </div>
          <Link href="/evidence">打开六维证据中心</Link>
        </div>
      </header>

      {error ? (
        <StatusMessage tone="error" title="学习执行暂时无法继续">
          {error}
        </StatusMessage>
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
          <label className="confirmation-row">
            <input
              type="checkbox"
              checked={confirmCodeExecution}
              disabled={busy}
              onChange={(event) =>
                setConfirmCodeExecution(event.target.checked)
              }
            />
            我确认本次执行会把代码发送到本机 Docker 隔离 Runner；不上传文件、不读取任意本地路径、不访问网络。
          </label>
          <p className="muted">
            数据根目录：{runnerAvailability?.data_root ?? "正在读取"}；占用{" "}
            {runnerAvailability?.used_gb ?? "未知"} GB；D 盘剩余{" "}
            {runnerAvailability?.free_gb ?? "未知"} GB。
          </p>
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
              !confirmCodeExecution ||
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
                : run.status === "paused"
                  ? `本次执行已暂停：${run.pause_reason ?? "未记录原因"}。暂停和延期都不记为能力失败。`
                : run.status === "completed"
                  ? "本次流程已完成；这不是掌握结论。"
                  : run.status === "ended"
                    ? "本次执行已明确结束且不可恢复，历史仍完整保留。"
                    : "按真实完成情况推进；未完成任务不会记作能力失败。"}
            </p>
          </section>

          {run.status === "paused" ? (
            <section className="run-state-control">
              <div>
                <span className="eyebrow">追加式暂停记录</span>
                <h3>学习执行已暂停</h3>
                <p>
                  暂停于{" "}
                  {run.paused_at
                    ? new Date(run.paused_at).toLocaleString("zh-CN")
                    : "未知时间"}
                  。恢复后会重新计算到期任务，逾期不算失败。
                </p>
              </div>
              <button
                className="primary-button"
                type="button"
                disabled={busy}
                onClick={resumeRun}
              >
                恢复学习执行
              </button>
            </section>
          ) : !["completed", "ended"].includes(run.status) ? (
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
              {availableMinutes > 120 ? (
                <div className="overtime-confirmation">
                  <label className="confirmation-row">
                    <input
                      type="checkbox"
                      checked={allowOvertime}
                      disabled={busy}
                      onChange={(event) => setAllowOvertime(event.target.checked)}
                    />
                    我明确确认今天超过默认 120 分钟预算。
                  </label>
                  <label>
                    超时原因
                    <input
                      type="text"
                      maxLength={500}
                      value={overtimeReason}
                      disabled={busy || !allowOvertime}
                      onChange={(event) => setOvertimeReason(event.target.value)}
                    />
                  </label>
                </div>
              ) : null}
              <button
                className="primary-button"
                type="button"
                disabled={
                  busy ||
                  (availableMinutes > 120 &&
                    (!allowOvertime || overtimeReason.trim().length === 0))
                }
                onClick={generateToday}
              >
                生成今日任务
              </button>
              {today ? (
                <p>
                  {today.reason} 当前选择 {today.tasks.length} 项，预计{" "}
                  {today.estimated_minutes} 分钟
                  {today.overtime ? "，已记录本日超时确认。" : "。"}
                </p>
              ) : null}
            </section>
          ) : null}

          {today?.deferred_tasks.length ? (
            <section className="deferred-task-list">
              <span className="eyebrow">追加式重排</span>
              <h3>今日延期任务</h3>
              <p>这些任务因预算或认知负荷限制顺延，不记为能力失败。</p>
              <ul>
                {today.deferred_tasks.map((task) => (
                  <li key={task.activity_id}>
                    <strong>{task.title}</strong>
                    <span>
                      {dailyPriorityLabels[task.daily_priority] ??
                        task.daily_priority}{" "}
                      · {task.estimated_minutes} 分钟 · {task.meaning}
                    </span>
                  </li>
                ))}
              </ul>
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
                      {activity.daily_priority
                        ? `${dailyPriorityLabels[activity.daily_priority] ?? activity.daily_priority} · `
                        : ""}
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
                  <p className="activity-scope">
                    能力范围：
                    {selectedActivity.capability_ids.join("、") ||
                      "不产生能力证据"}
                    ；语言：{selectedActivity.language}；证据上限：
                    {selectedActivity.evidence_ceiling}。
                  </p>
                  {selectedActivity.type === "code_text" ||
                  selectedActivity.type === "project_evidence" ? (
                    <div className="code-warning">
                      {selectedActivity.runner_task_id
                        ? "代码先作为不可信文本保存；只有点击隔离运行后才会进入断网、非 root、只读根文件系统的本地容器。"
                        : "这段代码仅作为不可信作品文本保存，不会执行或发送给外部 AI。"}
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
                        : selectedActivity.runner_task_id
                          ? "保存代码提交"
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
                  {selectedActivity.runner_task_id && latestAttempt ? (
                    <section className="runner-result" aria-live="polite">
                      <div className="answer-actions">
                        <button
                          className="primary-button"
                          type="button"
                          disabled={busy || !runnerAvailability?.available}
                          onClick={runLatestAttempt}
                        >
                          在隔离容器中运行最新提交
                        </button>
                        {!runnerAvailability?.available ? (
                          <span>
                            {runnerReasonLabels[
                              runnerAvailability?.reason_code ?? ""
                            ] ?? "Runner 当前不可用"}
                          </span>
                        ) : null}
                      </div>
                      {latestAttempt.runner_invocations.map((invocation) => (
                        <article key={invocation.id}>
                          <strong>
                            {invocation.task_id} · {invocation.status}
                          </strong>
                          <small>
                            {invocation.runtime_profile_id}@
                            {invocation.runtime_profile_version} · 制品摘要{" "}
                            {invocation.artifact_sha256.slice(0, 16)}…
                          </small>
                          {invocation.failure_code ? (
                            <p>失败码：{invocation.failure_code}</p>
                          ) : null}
                          {runnerTests(invocation).map((test, index) => (
                            <div key={`${invocation.id}:${String(test.id ?? index)}`}>
                              <strong>
                                {String(test.id ?? "test")} ·{" "}
                                {String(test.status ?? "unknown")}
                              </strong>
                              <span>标准输出</span>
                              <pre>{String(test.stdout ?? "")}</pre>
                              <span>标准错误</span>
                              <pre>{String(test.stderr ?? "")}</pre>
                            </div>
                          ))}
                        </article>
                      ))}
                    </section>
                  ) : null}
                  {executionMetadataRunId === run.id &&
                  stageCheckpoints.length > 0 &&
                  latestAttempt &&
                  selectedActivity.capability_ids.length > 0 ? (
                    <section className="independent-review-form">
                      <span className="eyebrow">外部真人评审</span>
                      <h4>记录当前活动的独立范围观察</h4>
                      <p>
                        只记录评审关系、精确能力范围、受管量表、结论和日期；不保存身份证明或附件。
                      </p>
                      <div className="review-form-grid">
                        <label>
                          评审者关系
                          <input
                            type="text"
                            maxLength={200}
                            value={reviewerRelationship}
                            disabled={busy}
                            onChange={(event) =>
                              setReviewerRelationship(event.target.value)
                            }
                          />
                        </label>
                        <label>
                          评审维度
                          <select
                            value={reviewDimension}
                            disabled={busy}
                            onChange={(event) =>
                              setReviewDimension(
                                event.target.value as typeof reviewDimension,
                              )
                            }
                          >
                            <option value="understanding">理解</option>
                            <option value="operation">操作</option>
                            <option value="transfer">迁移</option>
                            <option value="artifact">作品</option>
                            <option value="retention">保持</option>
                            <option value="correction">纠错</option>
                          </select>
                        </label>
                        <label>
                          结论
                          <select
                            value={reviewConclusion}
                            disabled={busy}
                            onChange={(event) =>
                              setReviewConclusion(
                                event.target.value as typeof reviewConclusion,
                              )
                            }
                          >
                            <option value="meets">观察项满足</option>
                            <option value="needs_work">需要改进</option>
                            <option value="uncertain">不确定</option>
                          </select>
                        </label>
                        <label>
                          评审时间
                          <input
                            type="datetime-local"
                            value={reviewedAt}
                            max={localDateTimeValue()}
                            disabled={busy}
                            onChange={(event) => setReviewedAt(event.target.value)}
                          />
                        </label>
                      </div>
                      <button
                        className="text-button"
                        type="button"
                        disabled={
                          busy ||
                          reviewerRelationship.trim().length === 0 ||
                          reviewedAt.length === 0
                        }
                        onClick={recordIndependentReview}
                      >
                        追加真人评审记录
                      </button>
                      {independentReviews
                        .filter((item) => item.activity_id === selectedActivity.id)
                        .map((item) => (
                          <p className="recorded-review" key={item.id}>
                            已记录：{item.dimension} · {item.conclusion} · 有效至{" "}
                            {new Date(item.expires_at).toLocaleDateString("zh-CN")}；
                            附件未保存。
                          </p>
                        ))}
                    </section>
                  ) : null}
                </article>
              ) : null}
            </section>
          ) : null}

          {!["paused", "completed", "ended"].includes(run.status) ? (
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

          {executionMetadataRunId === run.id && stageCheckpoints.length > 0 ? (
            <section className="stage-checkpoints">
              <span className="eyebrow">十二域阶段检查</span>
              <h3>共同主干初轮学习进度</h3>
              <p>阶段完成只描述流程进度，不表示该领域或整门算法掌握。</p>
              <div className="stage-checkpoint-grid">
                {stageCheckpoints.map((checkpoint) => (
                  <article key={checkpoint.domain_id}>
                    <span>{checkpointStatusLabels[checkpoint.status]}</span>
                    <strong>{checkpoint.title}</strong>
                    <small>
                      {checkpoint.completed_units}/{checkpoint.total_units} 个学习单元
                    </small>
                  </article>
                ))}
              </div>
            </section>
          ) : null}

          {executionMetadataRunId === run.id && branchGates ? (
            <section className="branch-gates">
              <span className="eyebrow">四分支准确门禁</span>
              <h3>共同主干后的入口资格</h3>
              <p>
                系统不会代替你选择分支；流程 completed、基础设施探针、自评或 AI
                评价都不能自动解锁。
              </p>
              <div className="branch-gate-grid">
                {branchGates.gates.map((gate) => (
                  <article key={gate.id}>
                    <header>
                      <strong>{gate.title}</strong>
                      <span>{gate.status === "eligible" ? "门禁满足，待用户选择" : "仍被阻断"}</span>
                    </header>
                    <dl>
                      <div>
                        <dt>已满足</dt>
                        <dd>{gate.satisfied_capability_ids.length}</dd>
                      </div>
                      <div>
                        <dt>过期</dt>
                        <dd>{gate.expired_capability_ids.length}</dd>
                      </div>
                      <div>
                        <dt>未来无效</dt>
                        <dd>{gate.future_invalid_capability_ids.length}</dd>
                      </div>
                      <div>
                        <dt>保持缺口</dt>
                        <dd>{gate.retained_shortfall}</dd>
                      </div>
                    </dl>
                    {gate.missing_requirements.length > 0 ? (
                      <details>
                        <summary>缺失能力要求（{gate.missing_requirements.length}）</summary>
                        <ul>
                          {gate.missing_requirements.map((item, index) => (
                            <li key={`${gate.id}:missing:${index}`}>
                              {requirementLabel(item)}
                            </li>
                          ))}
                        </ul>
                      </details>
                    ) : null}
                    {gate.missing_independent_reviews.length > 0 ? (
                      <details>
                        <summary>
                          缺少真人复核（{gate.missing_independent_reviews.length}）
                        </summary>
                        <ul>
                          {gate.missing_independent_reviews.map((item, index) => (
                            <li key={`${gate.id}:review:${index}`}>
                              {requirementLabel(item)}
                            </li>
                          ))}
                        </ul>
                      </details>
                    ) : null}
                    {gate.blocking_review_flags.length > 0 ? (
                      <p>待复核：{gate.blocking_review_flags.join("、")}</p>
                    ) : null}
                    <small>{gate.meaning}</small>
                  </article>
                ))}
              </div>
              {branchGates.limitations.map((item) => (
                <p className="muted" key={item}>
                  {item}
                </p>
              ))}
            </section>
          ) : null}

          {["active", "retention_pending"].includes(run.status) ? (
            <section className="pause-control">
              <label>
                暂停原因
                <input
                  type="text"
                  minLength={1}
                  maxLength={500}
                  value={pauseReason}
                  disabled={busy}
                  onChange={(event) => setPauseReason(event.target.value)}
                />
              </label>
              <button
                className="text-button"
                type="button"
                disabled={busy || pauseReason.trim().length === 0}
                onClick={pauseRun}
              >
                暂停并保留原因
              </button>
              <span>暂停不会删除任务、尝试、证据或审计历史。</span>
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

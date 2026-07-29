"use client";

import { useEffect, useMemo, useState } from "react";

import type {
  CapabilityScopeResponse,
  MarketSnapshotResponse,
  PathComparisonResponse,
  ReadinessEvaluationResponse,
  UserGoalResponse,
} from "@/generated/api-schema";
import {
  createPathComparison,
  createReadinessEvaluation,
  decidePathComparison,
  getCurrentReadinessGoal,
  getReadinessScopes,
  getSyntheticMarketSnapshots,
  messageForError,
  selectReadinessGoal,
} from "@/lib/api";
import {
  comparisonPaths,
  evidenceDimensions,
  type GoalKind,
  readinessStatusCopy,
  reasonCodeCopy,
} from "@/lib/readiness";

const GOALS: Array<{ value: GoalKind; label: string; description: string }> = [
  { value: "learning", label: "纯学习", description: "只关注能力成长与证据缺口" },
  { value: "exam", label: "准备考试", description: "不自动进入求职或变现比较" },
  { value: "employment", label: "就业准备", description: "只做本地合成路径比较" },
  { value: "freelancing", label: "接单准备", description: "不发布服务或联系客户" },
  { value: "productization", label: "产品化准备", description: "不收费或公开上架" },
  { value: "other", label: "其他目标", description: "由你填写当前目标" },
];

const DIMENSION_LABELS: Record<string, string> = {
  understanding: "知识理解",
  operation: "操作能力",
  transfer: "迁移能力",
  artifact: "作品证据",
  retention: "保持程度",
  correction: "纠错能力",
};

const PATH_LABELS: Record<string, string> = {
  employment: "就业",
  freelancing: "自由职业接单",
  productization: "产品化",
};

export function ReadinessPanel() {
  const [scopes, setScopes] = useState<Array<CapabilityScopeResponse>>([]);
  const [snapshots, setSnapshots] = useState<Array<MarketSnapshotResponse>>([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [goalKind, setGoalKind] = useState<GoalKind>("learning");
  const [customLabel, setCustomLabel] = useState("");
  const [goal, setGoal] = useState<UserGoalResponse | null>(null);
  const [selectedSnapshotId, setSelectedSnapshotId] = useState("");
  const [evaluation, setEvaluation] =
    useState<ReadinessEvaluationResponse | null>(null);
  const [comparison, setComparison] = useState<PathComparisonResponse | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");

  const selectedScope = useMemo(
    () => scopes.find((item) => item.learning_run_id === selectedRunId) ?? null,
    [scopes, selectedRunId],
  );
  const dimensions = evidenceDimensions(evaluation);
  const paths = comparisonPaths(comparison);
  const statusCopy = evaluation
    ? readinessStatusCopy(evaluation.status)
    : null;
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [scopeItems, snapshotItems] = await Promise.all([
          getReadinessScopes(),
          getSyntheticMarketSnapshots(),
        ]);
        if (cancelled) return;
        setScopes(scopeItems);
        setSnapshots(snapshotItems);
        setSelectedRunId(scopeItems[0]?.learning_run_id ?? "");
        setSelectedSnapshotId(
          snapshotItems.find((item) => item.freshness_status === "current")
            ?.id ??
            snapshotItems[0]?.id ??
            "",
        );
      } catch (cause) {
        if (!cancelled) setError(messageForError(cause));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedScope) return;
    let cancelled = false;
    void getCurrentReadinessGoal(
      selectedScope.skill_id,
      selectedScope.skill_version,
      selectedScope.capability_scope_id,
    )
      .then((item) => {
        if (cancelled) return;
        setGoal(item);
        if (item) {
          setGoalKind(item.goal_kind);
          setCustomLabel(item.custom_label ?? "");
        }
      })
      .catch((cause) => {
        if (!cancelled) setError(messageForError(cause));
      });
    return () => {
      cancelled = true;
    };
  }, [selectedScope]);

  async function saveGoal() {
    if (!selectedScope) return;
    setWorking(true);
    setError("");
    try {
      const created = await selectReadinessGoal({
        skill_id: selectedScope.skill_id,
        skill_version: selectedScope.skill_version,
        capability_scope_id: selectedScope.capability_scope_id,
        goal_kind: goalKind,
        custom_label: goalKind === "other" ? customLabel.trim() || null : null,
      });
      setGoal(created);
      setEvaluation(null);
      setComparison(null);
    } catch (cause) {
      setError(messageForError(cause));
    } finally {
      setWorking(false);
    }
  }

  async function evaluate() {
    if (!goal || !selectedScope) return;
    setWorking(true);
    setError("");
    try {
      const result = await createReadinessEvaluation({
        goal_selection_id: goal.id,
        learning_run_id: selectedScope.learning_run_id,
        market_snapshot_id: goal.market_comparison_applicable
          ? selectedSnapshotId || null
          : null,
      });
      setEvaluation(result);
      setComparison(null);
    } catch (cause) {
      setError(messageForError(cause));
    } finally {
      setWorking(false);
    }
  }

  async function compare() {
    if (!evaluation) return;
    setWorking(true);
    setError("");
    try {
      setComparison(
        await createPathComparison({ evaluation_id: evaluation.id }),
      );
    } catch (cause) {
      setError(messageForError(cause));
    } finally {
      setWorking(false);
    }
  }

  async function decide(decision: "accepted" | "rejected" | "deferred") {
    if (!comparison) return;
    setWorking(true);
    setError("");
    try {
      const item = await decidePathComparison(comparison.id, {
        decision,
        reason: null,
      });
      setComparison((current) =>
        current
          ? { ...current, decisions: [...current.decisions, item] }
          : current,
      );
    } catch (cause) {
      setError(messageForError(cause));
    } finally {
      setWorking(false);
    }
  }

  if (loading) {
    return (
      <section className="readiness-shell" aria-busy="true">
        <p className="empty-state">正在读取本地能力证据与合成夹具…</p>
      </section>
    );
  }

  if (scopes.length === 0) {
    return (
      <section className="readiness-shell">
        <h2>还没有可评估的能力范围</h2>
        <p className="empty-state">
          请先在学习面板创建一条 algorithm@0.2.0 学习记录。完成进度不会被当作掌握或变现资格。
        </p>
      </section>
    );
  }

  return (
    <section className="readiness-shell" aria-labelledby="readiness-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Local deterministic 5A</p>
          <h2 id="readiness-title">先选择目标，再决定比较是否适用。</h2>
        </div>
        <span className="boundary-badge">外部调用关闭</span>
      </div>

      {error ? (
        <div className="error-banner" role="alert">
          {error}
        </div>
      ) : null}

      <div className="readiness-form-grid">
        <label>
          能力范围
          <select
            value={selectedRunId}
            onChange={(event) => {
              setSelectedRunId(event.target.value);
              setGoal(null);
              setEvaluation(null);
              setComparison(null);
            }}
          >
            {scopes.map((item) => (
              <option key={item.learning_run_id} value={item.learning_run_id}>
                {item.scope_statement} · {item.learning_run_status}
              </option>
            ))}
          </select>
        </label>

        <label>
          当前目标
          <select
            value={goalKind}
            onChange={(event) => setGoalKind(event.target.value as GoalKind)}
          >
            {GOALS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label} — {item.description}
              </option>
            ))}
          </select>
        </label>

        {goalKind === "other" ? (
          <label>
            目标说明
            <input
              maxLength={200}
              value={customLabel}
              onChange={(event) => setCustomLabel(event.target.value)}
              placeholder="例如：完成一次校内课程考核"
            />
          </label>
        ) : null}

        <button
          className="primary-button"
          disabled={working || (goalKind === "other" && !customLabel.trim())}
          onClick={() => void saveGoal()}
          type="button"
        >
          保存目标
        </button>
      </div>

      {goal ? (
        <article className="goal-summary">
          <strong>已保存：{GOALS.find((item) => item.value === goal.goal_kind)?.label}</strong>
          <p>
            {goal.market_comparison_applicable
              ? "你主动选择了变现相关目标；系统仍只会使用合成数据进行本地比较。"
              : "这是非变现目标；系统不会强制生成就业、接单或产品化建议。"}
          </p>
        </article>
      ) : (
        <p className="empty-state">请先保存当前目标。</p>
      )}

      {goal?.market_comparison_applicable ? (
        <div className="synthetic-selector">
          <label>
            合成测试快照
            <select
              value={selectedSnapshotId}
              onChange={(event) => setSelectedSnapshotId(event.target.value)}
            >
              {snapshots.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label} · {item.freshness_status}
                </option>
              ))}
            </select>
          </label>
          <p>
            所有选项都是规则测试夹具，不是市场事实。过期、冲突或无法判断夹具会阻断比较。
          </p>
        </div>
      ) : null}

      <button
        className="secondary-button"
        disabled={working || !goal}
        onClick={() => void evaluate()}
        type="button"
      >
        生成准备度评估
      </button>

      {evaluation && statusCopy ? (
        <section className="readiness-result" aria-live="polite">
          <div className={`readiness-status status-${evaluation.status}`}>
            <p className="eyebrow">{evaluation.status}</p>
            <h3>{statusCopy.title}</h3>
            <p>{statusCopy.description}</p>
          </div>

          <div className="reason-list">
            <h3>确定性依据</h3>
            <ul>
              {evaluation.reason_codes.map((code) => (
                <li key={code}>{reasonCodeCopy(code)}</li>
              ))}
            </ul>
          </div>

          <div className="evidence-grid" aria-label="六维证据快照">
            {dimensions.map((item) => (
              <article key={item.dimension}>
                <h3>{DIMENSION_LABELS[item.dimension] ?? item.dimension}</h3>
                <p>
                  等级：<strong>{item.evidence_level}</strong> · 数量：
                  {item.evidence_count}
                </p>
                <p>
                  复核标记：
                  {item.review_flags.length > 0
                    ? item.review_flags.join("、")
                    : "无"}
                </p>
              </article>
            ))}
          </div>

          {evaluation.status === "comparison_ready" ? (
            <button
              className="primary-button"
              disabled={working}
              onClick={() => void compare()}
              type="button"
            >
              生成三路径合成比较
            </button>
          ) : null}
        </section>
      ) : null}

      {comparison ? (
        <section className="comparison-result" aria-labelledby="comparison-title">
          <div className="synthetic-warning">
            <strong id="comparison-title">合成比较，不是真实市场结论</strong>
            <p>不保证工作、订单、需求、价格或收入，也不会创建任何真实实验。</p>
          </div>
          <div className="comparison-grid">
            {paths.map((item) => (
              <article
                className={item.selected_goal ? "selected-path" : ""}
                key={item.path}
              >
                <h3>{PATH_LABELS[item.path] ?? item.path}</h3>
                {item.selected_goal ? <span>你当前选择的方向</span> : null}
                <h4>证据缺口</h4>
                <ul>
                  {item.evidence_gaps.map((gap) => (
                    <li key={gap}>{gap}</li>
                  ))}
                </ul>
                <h4>合成因素</h4>
                <ul>
                  {item.factors.map((factor, index) => (
                    <li key={`${item.path}-factor-${index}`}>
                      {String(factor.dimension ?? "unknown")}：
                      {String(factor.signal ?? "unknown")}
                    </li>
                  ))}
                </ul>
                <h4>不确定性</h4>
                <ul>
                  {item.uncertainties.map((value) => (
                    <li key={value}>{value}</li>
                  ))}
                </ul>
              </article>
            ))}
          </div>
          <div className="decision-actions" aria-label="比较决定">
            <button disabled={working} onClick={() => void decide("accepted")} type="button">
              接受本地比较
            </button>
            <button disabled={working} onClick={() => void decide("deferred")} type="button">
              延后
            </button>
            <button disabled={working} onClick={() => void decide("rejected")} type="button">
              拒绝
            </button>
          </div>
          {comparison.decisions.length > 0 ? (
            <p className="audit-note">
              已保留 {comparison.decisions.length} 条追加式决定记录；决定不会触发投递、发布或交易。
            </p>
          ) : null}
        </section>
      ) : null}

      <aside className="notice">
        5B、5C、真实模型、市场来源与预算仍未授权。4B 也未授权，因此代码文本不会被执行，
        真实算法交付资格不会被推断。
      </aside>
    </section>
  );
}

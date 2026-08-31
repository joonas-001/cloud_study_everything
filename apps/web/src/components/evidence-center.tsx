"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { CapabilityProfile } from "@/components/capability-profile";
import { StatusMessage } from "@/components/status-message";
import type {
  CapabilityProfileResponse,
  ExperimentResponse,
  LearningEvidenceResponse,
  LearningRunResponse,
} from "@/generated/api-schema";
import {
  getLatestLearningRun,
  getCapabilityProfile,
  getLearningEvidence,
  listExperiments,
  messageForError,
} from "@/lib/api";
import {
  DIMENSION_COPY,
  dimensionEvidence,
  EVIDENCE_DIMENSIONS,
  EVIDENCE_LEVEL_COPY,
  EVIDENCE_STRENGTH_COPY,
  evidenceActivityTitle,
  evidenceUpdatedAt,
  REVIEW_FLAG_COPY,
} from "@/lib/evidence";

function formatTime(value: string | null): string {
  if (!value) {
    return "尚无更新时间";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "时间不可用";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function EvidenceCenter({
  skillId,
  skillVersion,
}: Readonly<{ skillId: string; skillVersion: string }>) {
  const [run, setRun] = useState<LearningRunResponse | null>(null);
  const [evidence, setEvidence] = useState<LearningEvidenceResponse | null>(null);
  const [profile, setProfile] = useState<CapabilityProfileResponse | null>(null);
  const [experiments, setExperiments] = useState<ExperimentResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([getLatestLearningRun(skillId, skillVersion), listExperiments()])
      .then(async ([nextRun, nextExperiments]) => {
        const [nextEvidence, nextProfile] = nextRun
          ? await Promise.all([
              getLearningEvidence(nextRun.id),
              getCapabilityProfile(nextRun.id),
            ])
          : [null, null];
        if (!active) {
          return;
        }
        setRun(nextRun);
        setEvidence(nextEvidence);
        setProfile(nextProfile);
        setExperiments(
          nextExperiments.filter(
            (item) =>
              item.skill_id === skillId && item.skill_version === skillVersion,
          ),
        );
      })
      .catch((reason: unknown) => {
        if (active) {
          setError(messageForError(reason));
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [skillId, skillVersion]);

  const externalReviews = useMemo(
    () =>
      experiments.flatMap((experiment) =>
        experiment.reviews.map((review) => ({ experiment, review })),
      ),
    [experiments],
  );
  const dimensions = evidence?.dimensions ?? run?.dimensions ?? [];
  const currentEvidence = evidence?.evidence ?? [];
  const flags = new Set(dimensions.flatMap((dimension) => dimension.review_flags));

  if (loading) {
    return (
      <section className="panel loading-panel" role="status" aria-live="polite" aria-busy="true">
        <span className="loading-dot" aria-hidden="true" />
        正在读取最新执行证据……
      </section>
    );
  }

  if (error) {
    return (
      <StatusMessage tone="error" title="证据中心暂时无法读取">
        {error}
      </StatusMessage>
    );
  }

  if (!run || !evidence) {
    return (
      <section className="m7-empty-state evidence-empty-state">
        <span className="eyebrow">No learning run</span>
        <h2>还没有可汇总的学习执行</h2>
        <p>
          这里不会把“没有执行记录”解释成“没有能力”。创建学习执行并产生证据后，六维中心才会展示真实记录。
        </p>
        <Link href="/learning">进入学习工作区</Link>
      </section>
    );
  }

  return (
    <div className="evidence-center">
      <section className="evidence-scope-bar" aria-label="证据适用范围">
        <div>
          <span>当前视图</span>
          <strong>最新学习执行</strong>
          <small>现有 API 不提供全历史执行列表，不伪装为全历史汇总。</small>
        </div>
        <div>
          <span>精确版本</span>
          <strong>
            {run.skill_id}@{run.skill_version}
          </strong>
          <small>锁摘要 {run.lock_sha256.slice(0, 16)}…</small>
        </div>
        <div>
          <span>执行状态</span>
          <strong>{run.status}</strong>
          <small>更新于 {formatTime(evidenceUpdatedAt(dimensions))}</small>
        </div>
      </section>

      <section className="evidence-board" aria-labelledby="six-dimension-title">
        <header className="evidence-board__header">
          <div>
            <span className="eyebrow">Six dimensions</span>
            <h2 id="six-dimension-title">六维能力证据</h2>
          </div>
          <p>等级、数量和待办分别展示。任何单项记录都不能外推为整门算法掌握。</p>
        </header>
        <div className="evidence-dimension-board">
          {EVIDENCE_DIMENSIONS.map((dimensionId) => {
            const dimension = dimensions.find(
              (item) => item.dimension === dimensionId,
            ) ?? {
                dimension: dimensionId,
                evidence_count: 0,
                evidence_level: "none" as const,
                review_flags: [],
                updated_at: run.created_at,
              };
            const records = dimensionEvidence(dimensionId, currentEvidence);
            const level = EVIDENCE_LEVEL_COPY[dimension.evidence_level];
            return (
              <article
                className={`evidence-dimension evidence-level--${dimension.evidence_level}`}
                key={dimensionId}
              >
                <header>
                  <div>
                    <span>{DIMENSION_COPY[dimensionId].title}</span>
                    <h3>{level.label}</h3>
                  </div>
                  <strong aria-label={`${level.order} / 4`}>
                    {level.order}
                    <small>/4</small>
                  </strong>
                </header>
                <p>{DIMENSION_COPY[dimensionId].question}</p>
                <div className="evidence-meter" aria-hidden="true">
                  <span style={{ width: `${level.order * 25}%` }} />
                </div>
                <dl>
                  <div>
                    <dt>当前记录</dt>
                    <dd>{dimension.evidence_count} 条</dd>
                  </div>
                  <div>
                    <dt>最近更新</dt>
                    <dd>{formatTime(dimension.updated_at)}</dd>
                  </div>
                </dl>
                <p className="evidence-boundary">{level.boundary}</p>
                {dimension.review_flags.length ? (
                  <ul className="evidence-flags">
                    {dimension.review_flags.map((flag) => (
                      <li key={flag}>{REVIEW_FLAG_COPY[flag]}</li>
                    ))}
                  </ul>
                ) : (
                  <span className="evidence-no-flag">当前无附加待办</span>
                )}
                {records.length ? (
                  <details>
                    <summary>查看该维度记录</summary>
                    <ol>
                      {records.map((item) => (
                        <li key={item.id}>
                          <strong>
                            {evidenceActivityTitle(item, run.activities)}
                          </strong>
                          <span>
                            {EVIDENCE_STRENGTH_COPY[item.strength]} · {item.method} ·{" "}
                            {item.result}
                          </span>
                          <small>
                            {formatTime(item.created_at)} · 标准 {item.criterion_id}
                          </small>
                        </li>
                      ))}
                    </ol>
                  </details>
                ) : null}
              </article>
            );
          })}
        </div>
      </section>

      <section className="evidence-followups" aria-labelledby="evidence-followups-title">
        <header>
          <div>
            <span className="eyebrow">Evidence follow-ups</span>
            <h2 id="evidence-followups-title">待办与独立验证</h2>
          </div>
          <span>{flags.size} 类当前待办</span>
        </header>
        <div className="evidence-followups__grid">
          <article>
            <h3>当前待办</h3>
            {flags.size ? (
              <ul>
                {Array.from(flags).map((flag) => (
                  <li key={flag}>{REVIEW_FLAG_COPY[flag]}</li>
                ))}
              </ul>
            ) : (
              <p>最新执行的六维快照没有附加待办；这不表示所有掌握标准已满足。</p>
            )}
          </article>
          <article>
            <h3>外部真人评审</h3>
            {externalReviews.length ? (
              <ul>
                {externalReviews.map(({ experiment, review }) => (
                  <li key={review.id}>
                    <strong>
                      {review.dimension === "transfer" ? "迁移" : "作品"} ·{" "}
                      {review.conclusion === "passed" ? "通过" : "需改进"}
                    </strong>
                    <span>{review.review_scope}</span>
                    <small>
                      {review.rubric_id}@{review.rubric_version} ·{" "}
                      {formatTime(review.reviewed_at)} · 实验{" "}
                      {experiment.id.slice(0, 8)}
                    </small>
                  </li>
                ))}
              </ul>
            ) : (
              <p>
                当前没有与该精确技能版本关联的外部真人评审。用户自评和 AI
                自评不能替代独立验证。
              </p>
            )}
          </article>
        </div>
      </section>

      <section
        className="evidence-limitations"
        aria-labelledby="evidence-limitations-title"
      >
        <div>
          <span className="eyebrow">Boundaries</span>
          <h2 id="evidence-limitations-title">当前不能证明什么</h2>
        </div>
        <ul>
          {evidence.limitations.map((item) => (
            <li key={item}>{item}</li>
          ))}
          <li>
            证据中心不产生 scope_criteria_met，不自动解锁分支、5C 或真实外部动作。
          </li>
          <li>外部真人评审单独展示，不会静默抬高学习执行的六维等级。</li>
        </ul>
      </section>

      {profile ? <CapabilityProfile profile={profile} /> : null}
    </div>
  );
}

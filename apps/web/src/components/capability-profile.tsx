"use client";

import { useState } from "react";

import type {
  CapabilityProfileItemResponse,
  CapabilityProfileResponse,
} from "@/generated/api-schema";
import { exportCapabilityProfile, messageForError } from "@/lib/api";
import {
  DIMENSION_COPY,
  EVIDENCE_LEVEL_COPY,
  REVIEW_FLAG_COPY,
  type EvidenceDimensionId,
} from "@/lib/evidence";

function numeric(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function formatTime(value: string | null): string {
  if (!value) return "尚无";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "时间不可用";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

function capabilityEvidenceCount(capability: CapabilityProfileItemResponse): number {
  return capability.dimensions.reduce((total, item) => total + item.evidence_count, 0);
}

function capabilityFlags(capability: CapabilityProfileItemResponse): string[] {
  return Array.from(new Set(capability.dimensions.flatMap((item) => item.review_flags)));
}

export function CapabilityProfile({
  profile,
}: Readonly<{ profile: CapabilityProfileResponse }>) {
  const [exporting, setExporting] = useState<"json" | "csv" | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  async function download(format: "json" | "csv") {
    setExporting(format);
    setExportError(null);
    try {
      const blob = await exportCapabilityProfile(profile.run_id, format);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `cloud-study-capability-profile-${profile.skill_id}-${profile.skill_version}.${format}`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (reason: unknown) {
      setExportError(messageForError(reason));
    } finally {
      setExporting(null);
    }
  }

  const summary = profile.summary;
  const alignment = profile.plan_alignment;
  const shadow = profile.shadow_evaluation;

  return (
    <section className="capability-profile print-surface" aria-labelledby="capability-profile-title">
      <header className="capability-profile__header">
        <div>
          <span className="eyebrow">Scoped capability profile · milestone 8E</span>
          <h2 id="capability-profile-title">范围化能力档案</h2>
          <p>
            档案只汇总当前执行与精确版本的结构化证据，不包含提交正文、密钥、金额，也不生成证书或公开链接。
          </p>
        </div>
        <div className="capability-profile__actions no-print" aria-label="档案导出操作">
          <button
            className="secondary-button"
            disabled={exporting !== null}
            onClick={() => void download("json")}
            type="button"
          >
            {exporting === "json" ? "正在导出…" : "导出 JSON"}
          </button>
          <button
            className="secondary-button"
            disabled={exporting !== null}
            onClick={() => void download("csv")}
            type="button"
          >
            {exporting === "csv" ? "正在导出…" : "导出 CSV"}
          </button>
          <button className="secondary-button" onClick={() => window.print()} type="button">
            本地打印
          </button>
        </div>
      </header>

      {exportError ? (
        <p className="error-banner" role="alert">
          {exportError}
        </p>
      ) : null}

      <div className="capability-profile__scope" aria-label="档案精确范围">
        <div>
          <span>精确技能版本</span>
          <strong>{profile.skill_id}@{profile.skill_version}</strong>
          <small>{profile.skill_title}</small>
        </div>
        <div>
          <span>执行与内容锁</span>
          <strong>{profile.run_status}</strong>
          <small>{profile.lock_sha256 ? `${profile.lock_sha256.slice(0, 16)}…` : "历史锁缺失"}</small>
        </div>
        <div>
          <span>范围状态</span>
          <strong>{profile.scope_status === "scoped" ? "能力 ID 已范围化" : "历史记录未范围化"}</strong>
          <small>生成于 {formatTime(profile.generated_at)}</small>
        </div>
      </div>

      <div className="capability-profile__metrics" aria-label="档案摘要">
        <article>
          <span>能力范围</span>
          <strong>{numeric(summary.capability_count)}</strong>
          <small>有证据 {numeric(summary.evidenced_capability_count)} 项</small>
        </article>
        <article>
          <span>尝试</span>
          <strong>{numeric(summary.attempt_count)}</strong>
          <small>只计结构化学习尝试</small>
        </article>
        <article>
          <span>当前证据</span>
          <strong>{numeric(summary.active_evidence_count)}</strong>
          <small>已排除被后续纠错取代的记录</small>
        </article>
        <article>
          <span>独立真人评审</span>
          <strong>{numeric(summary.independent_review_count)}</strong>
          <small>自评与 AI 自评不计入</small>
        </article>
      </div>

      <section className="capability-profile__analysis" aria-labelledby="learning-analysis-title">
        <div>
          <span className="eyebrow">Learning effect analysis</span>
          <h3 id="learning-analysis-title">计划偏差用于重排，不用于惩罚</h3>
        </div>
        <dl>
          <div>
            <dt>计划估算</dt>
            <dd>{numeric(alignment.scheduled_estimated_minutes)} 分钟</dd>
          </div>
          <div>
            <dt>已完成任务估算</dt>
            <dd>{numeric(alignment.completed_estimated_minutes)} 分钟</dd>
          </div>
          <div>
            <dt>待完成估算</dt>
            <dd>{numeric(alignment.unfinished_estimated_minutes)} 分钟</dd>
          </div>
        </dl>
        <p>{String(alignment.meaning ?? "不使用页面停留时长推断掌握。")}</p>
      </section>

      <div className="capability-domain-list">
        {profile.domains.map((domain) => {
          const evidenced = domain.capabilities.filter(capabilityEvidenceCount).length;
          return (
            <details className="capability-domain" key={domain.id} open={evidenced > 0}>
              <summary>
                <span>
                  <strong>{domain.title}</strong>
                  <small>{domain.id} · {domain.capabilities.length} 个范围</small>
                </span>
                <span>{evidenced} 个已有证据</span>
              </summary>
              <div className="capability-domain__grid">
                {domain.capabilities.map((capability) => (
                  <article className="capability-card" key={capability.id}>
                    <header>
                      <div>
                        <span>{capability.id}</span>
                        <h4>{capability.title}</h4>
                      </div>
                      <strong>{capabilityEvidenceCount(capability)} 条</strong>
                    </header>
                    <div className="capability-card__levels" aria-label="六维范围证据">
                      {capability.dimensions
                        .filter((item) => item.evidence_level !== "none")
                        .map((item) => (
                          <span key={item.dimension}>
                            {DIMENSION_COPY[item.dimension as EvidenceDimensionId].title}：
                            {EVIDENCE_LEVEL_COPY[item.evidence_level].label}
                            {item.expired_count ? `（${item.expired_count} 条过期）` : ""}
                          </span>
                        ))}
                      {capabilityEvidenceCount(capability) === 0 ? (
                        <span>当前无该能力范围的结构化证据；不等于能力不存在。</span>
                      ) : null}
                      {capabilityFlags(capability).map((flag) => (
                        <span key={flag}>
                          待办：{REVIEW_FLAG_COPY[flag as keyof typeof REVIEW_FLAG_COPY] ?? flag}
                        </span>
                      ))}
                    </div>
                    <dl className="capability-card__analytics">
                      <div><dt>尝试</dt><dd>{capability.analytics.attempt_count}</dd></div>
                      <div><dt>通过</dt><dd>{capability.analytics.passed_count}</dd></div>
                      <div><dt>失败</dt><dd>{capability.analytics.failed_count}</dd></div>
                      <div><dt>不确定</dt><dd>{capability.analytics.uncertain_count}</dd></div>
                      <div><dt>纠错</dt><dd>{capability.analytics.correction_count}</dd></div>
                      <div><dt>逾期复测</dt><dd>{capability.analytics.review_overdue_count}</dd></div>
                    </dl>
                    <p className="capability-card__proof"><strong>能证明：</strong>{capability.can_prove}</p>
                    <p className="capability-card__limit"><strong>不能证明：</strong>{capability.cannot_prove[0]}</p>
                    {capability.evidence.length ? (
                      <details className="capability-card__records">
                        <summary>查看范围记录与验证方式</summary>
                        <ol>
                          {capability.evidence.map((item) => (
                            <li key={item.id}>
                              <strong>{DIMENSION_COPY[item.dimension as EvidenceDimensionId]?.title ?? item.dimension} · {item.strength}</strong>
                              <span>{item.method} / {item.result} / {item.language}</span>
                              <small>
                                {formatTime(item.created_at)} · {item.expired ? "已过期" : `有效至 ${formatTime(item.expires_at)}`}
                              </small>
                              {item.runner ? (
                                <small>
                                  Runner {String(item.runner.runtime_profile_id ?? "未知运行时")}@
                                  {String(item.runner.runtime_profile_version ?? "未知版本")} ·
                                  协议 {String(item.runner.protocol_version ?? "未知")}
                                </small>
                              ) : null}
                            </li>
                          ))}
                        </ol>
                      </details>
                    ) : null}
                  </article>
                ))}
              </div>
            </details>
          );
        })}
      </div>

      <section className="shadow-evaluation" aria-labelledby="shadow-evaluation-title">
        <div>
          <span className="eyebrow">Review shadow evaluation</span>
          <h3 id="shadow-evaluation-title">复习候选只做隔离影子评估</h3>
        </div>
        <div>
          <strong>{shadow.status === "insufficient_data" ? "样本不足，不形成比较结论" : "已有离线候选比较样本"}</strong>
          <p>
            当前 {shadow.sample_count} 个最小化复习结果样本；候选预测和记忆概率均不向界面暴露。
            权威任务仍固定为 1、2、4、7、15 天。
          </p>
          <small>
            {shadow.model_id}@{shadow.model_version} · 模型锁 {shadow.model_sha256.slice(0, 16)}…
          </small>
        </div>
        <ul>
          <li>是否影响任务：{shadow.affects_tasks ? "是" : "否"}</li>
          <li>是否影响证据：{shadow.affects_evidence ? "是" : "否"}</li>
          <li>是否影响用户结论：{shadow.affects_user_conclusions ? "是" : "否"}</li>
        </ul>
      </section>

      <section className="capability-profile__limitations">
        <h3>档案边界</h3>
        <ul>{profile.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
      </section>
    </section>
  );
}

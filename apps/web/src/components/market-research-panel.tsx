"use client";

import { useEffect, useMemo, useState } from "react";

import type {
  AiProviderProfileResponse,
  MarketResearchHistoryResponse,
  MarketResearchOverviewResponse,
  MarketResearchRunResponse,
} from "@/generated/api-schema";
import {
  ApiError,
  completeMarketResearchMetadataOnly,
  createMarketResearchRun,
  getAiProviderProfiles,
  getMarketResearchOverview,
  getMarketResearchHistory,
  getPrivacySettings,
  messageForError,
  redactMarketResearchSource,
  recoverPreDispatchMarketResearch,
  reconcileMarketResearchRecovery,
  reviewMarketResearch,
  synthesizeMarketResearch,
} from "@/lib/api";

const statusLabels: Record<MarketResearchRunResponse["status"], string> = {
  source_pending: "正在检查官方来源",
  synthesis_pending: "官方材料已就绪，等待你确认 AI 综合",
  synthesis_in_progress: "DeepSeek 综合进行中，请勿重复提交",
  recovery_required: "付费调用状态未知，等待你确认对账结束",
  review_pending: "AI 综合待人工复核",
  completed: "本次研究已结束",
  blocked: "来源不足，已阻断",
  failed: "本次研究已停止",
};

const dataCategoryLabels: Record<string, string> = {
  locked_skill_and_goal_context: "锁定的技能、能力范围与当前目标",
  approved_market_scope: "已批准的市场范围",
  official_source_metadata: "官方来源 ID、所有者、适用路径与限制",
  sanitized_short_excerpts: "最多 2000 字符的净化短摘录",
  api_credentials: "API 密钥或凭据引用",
  raw_source_documents: "官方来源原始全文",
  learning_records: "学习记录与作答内容",
  local_file_paths: "本地文件路径",
  unrelated_personal_data: "与研究无关的个人数据",
};

const invalidSynthesisFailureCodes = new Set([
  "deepseek_content_missing",
  "deepseek_content_not_json",
  "deepseek_limited_protocol_invalid",
  "deepseek_canonical_synthesis_invalid",
]);

function yuan(micros: unknown): string {
  return typeof micros === "number" ? `¥${(micros / 1_000_000).toFixed(4)}` : "—";
}

function strings(value: unknown): Array<string> {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function localTime(value: string | null): string {
  return value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "尚无";
}

function remainingTime(seconds: number): string {
  if (seconds <= 0) {
    return "现在";
  }
  const hours = Math.ceil(seconds / 3600);
  return hours < 48 ? `约 ${hours} 小时` : `约 ${Math.ceil(hours / 24)} 天`;
}

export function MarketResearchPanel() {
  const [overview, setOverview] = useState<MarketResearchOverviewResponse | null>(
    null,
  );
  const [profiles, setProfiles] = useState<Array<AiProviderProfileResponse>>([]);
  const [history, setHistory] = useState<MarketResearchHistoryResponse>({
    runs: [],
    events: [],
  });
  const [externalAiEnabled, setExternalAiEnabled] = useState(false);
  const [profileId, setProfileId] = useState("");
  const [goalSelectionId, setGoalSelectionId] = useState("");
  const [confirmSources, setConfirmSources] = useState(false);
  const [confirmAi, setConfirmAi] = useState(false);
  const [confirmPreDispatchRecovery, setConfirmPreDispatchRecovery] =
    useState(false);
  const [redactionSourceId, setRedactionSourceId] = useState("");
  const [reviewNote, setReviewNote] = useState("");
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const approvedProfiles = useMemo(
    () =>
      profiles.filter(
        (profile) =>
          profile.enabled &&
          profile.executable &&
          profile.provider_id === "deepseek" &&
          profile.model_id === "deepseek-v4-flash" &&
          profile.base_url === "https://api.deepseek.com" &&
          profile.credential_reference,
      ),
    [profiles],
  );
  const run = overview?.latest_run ?? null;
  const budget = overview?.budget ?? {};
  const sourceAccessPolicy = overview?.source_access_policy ?? null;
  const sourceAccessById = new Map(
    (sourceAccessPolicy?.sources ?? []).map((source) => [source.source_id, source]),
  );
  const warningRatios = Array.isArray(budget.warning_ratios_reached)
    ? budget.warning_ratios_reached.filter(
        (item): item is number => typeof item === "number",
      )
    : [];
  const catalog = overview?.catalog ?? {};
  const contexts = (overview?.available_contexts ?? []) as Array<
    Record<string, unknown>
  >;
  const selectedContext =
    contexts.find(
      (item) => String(item.goal_selection_id) === goalSelectionId,
    ) ?? null;
  const scope =
    typeof catalog.scope === "object" && catalog.scope !== null
      ? (catalog.scope as Record<string, unknown>)
      : {};
  const evidenceCapabilities =
    typeof catalog.path_evidence_capabilities === "object" &&
    catalog.path_evidence_capabilities !== null
      ? (catalog.path_evidence_capabilities as Record<
          string,
          Record<string, unknown>
        >)
      : {};
  const catalogSources = Array.isArray(catalog.sources)
    ? (catalog.sources as Array<Record<string, unknown>>)
    : [];
  const outboundPreview =
    run &&
    typeof run.outbound_material_preview === "object" &&
    run.outbound_material_preview !== null
      ? (run.outbound_material_preview as Record<string, unknown>)
      : {};
  const outboundMaterials = Array.isArray(outboundPreview.materials)
    ? (outboundPreview.materials as Array<Record<string, unknown>>)
    : [];
  const sentDataCategories = strings(outboundPreview.sent_data_categories);
  const excludedDataCategories = strings(outboundPreview.excluded_data_categories);

  useEffect(() => {
    let active = true;
    Promise.all([
      getMarketResearchOverview(),
      getMarketResearchHistory(),
      getAiProviderProfiles(),
      getPrivacySettings(),
    ])
      .then(([nextOverview, nextHistory, nextProfiles, privacy]) => {
        if (!active) {
          return;
        }
        setOverview(nextOverview);
        setHistory(nextHistory);
        setProfiles(nextProfiles);
        setExternalAiEnabled(privacy.external_ai_enabled);
        const firstContext = nextOverview.available_contexts[0] as
          | Record<string, unknown>
          | undefined;
        setGoalSelectionId(
          firstContext ? String(firstContext.goal_selection_id) : "",
        );
        const first = nextProfiles.find(
          (profile) =>
            profile.enabled &&
            profile.provider_id === "deepseek" &&
            profile.model_id === "deepseek-v4-flash" &&
            profile.credential_reference,
        );
        setProfileId(first?.id ?? "");
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
  }, []);

  useEffect(() => {
    if (!goalSelectionId) {
      return;
    }
    let active = true;
    getMarketResearchOverview(goalSelectionId)
      .then((nextOverview) => {
        if (active) {
          setOverview(nextOverview);
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
  }, [goalSelectionId]);

  async function runAction(action: () => Promise<MarketResearchRunResponse>) {
    setBusy(true);
    setError(null);
    try {
      const latest = await action();
      const [nextOverview, nextHistory] = await Promise.all([
        getMarketResearchOverview(goalSelectionId || undefined),
        getMarketResearchHistory(),
      ]);
      setOverview({ ...nextOverview, latest_run: latest });
      setHistory(nextHistory);
    } catch (reason: unknown) {
      const originalError = messageForError(reason);
      if (reason instanceof ApiError) {
        try {
          const [nextOverview, nextHistory] = await Promise.all([
            getMarketResearchOverview(goalSelectionId || undefined),
            getMarketResearchHistory(),
          ]);
          setOverview(nextOverview);
          setHistory(nextHistory);
        } catch {
          // Preserve the original server-side failure; a refresh failure must not hide it.
        }
      }
      setError(originalError);
    } finally {
      setBusy(false);
    }
  }

  function startSourceCheck() {
    void runAction(async () => {
      const created = await createMarketResearchRun({
        provider_profile_id: profileId,
        goal_selection_id: String(selectedContext?.goal_selection_id ?? ""),
        catalog_id: String(selectedContext?.catalog_id ?? ""),
        catalog_version: String(selectedContext?.catalog_version ?? ""),
        readiness_evaluation_id:
          selectedContext?.readiness_evaluation_id == null
            ? null
            : String(selectedContext.readiness_evaluation_id),
        confirm_external_sources: confirmSources,
      });
      setConfirmSources(false);
      return created;
    });
  }

  function synthesize() {
    if (!run) {
      return;
    }
    void runAction(async () => {
      const synthesized = await synthesizeMarketResearch(run.id, {
        confirm_external_ai: confirmAi,
      });
      setConfirmAi(false);
      return synthesized;
    });
  }

  function recoverPreDispatch() {
    if (!run) {
      return;
    }
    void runAction(async () => {
      const recovered = await recoverPreDispatchMarketResearch(run.id, {
        confirm_recovery: confirmPreDispatchRecovery,
      });
      setConfirmPreDispatchRecovery(false);
      setConfirmAi(false);
      return recovered;
    });
  }

  function review(decision: "accepted" | "rejected") {
    if (!run) {
      return;
    }
    void runAction(() =>
      reviewMarketResearch(run.id, {
        decision,
        note: reviewNote || null,
      }),
    );
  }

  function redactSource(sourceId: string) {
    if (!run || redactionSourceId !== sourceId) {
      return;
    }
    void runAction(async () => {
      const redacted = await redactMarketResearchSource(run.id, sourceId, {
        confirm_redaction: true,
        reason: "用户从本地市场研究界面明确删除已保存摘录。",
      });
      setRedactionSourceId("");
      setConfirmAi(false);
      return redacted;
    });
  }

  const canRecoverPreDispatch =
    run?.status === "failed" &&
    run.failure_code === "pricing_changed_or_unverifiable" &&
    run.actual_cost_micros === 0 &&
    run.accounted_cost_micros === 0;
  const canOfferStart =
    Boolean(selectedContext) &&
    (!run ||
      ["completed", "blocked", "failed"].includes(run.status)) &&
    !canRecoverPreDispatch;
  const sourceAccessBlocked = sourceAccessPolicy?.blocked ?? false;

  return (
    <div className="market-research-layout">
      {error ? (
        <div className="error-banner" role="alert">
          <strong>研究未继续</strong>
          <span>{error}</span>
        </div>
      ) : null}

      <section className="panel research-governance">
        <div className="section-heading">
          <div>
            <span className="eyebrow">Approved scope</span>
            <h2>中国大陆市场范围与费用硬上限</h2>
          </div>
          <span className="status">仅 DeepSeek V4 Flash</span>
        </div>
        <div className="research-metrics">
          <article>
            <span>月累计 / 上限</span>
            <strong>
              {yuan(budget.monthly_used_micros)} /{" "}
              {yuan(budget.monthly_limit_micros)}
            </strong>
          </article>
          <article>
            <span>日累计 / 上限</span>
            <strong>
              {yuan(budget.daily_used_micros)} / {yuan(budget.daily_limit_micros)}
            </strong>
          </article>
          <article>
            <span>单次研究上限</span>
            <strong>{yuan(budget.run_limit_micros)}</strong>
          </article>
        </div>
        <div className="research-scope">
          <p>
            <strong>研究上下文：</strong>
            {selectedContext
              ? `${String(selectedContext.skill_id)}@${String(
                  selectedContext.skill_version,
                )} · ${String(selectedContext.capability_scope_id)}`
              : "尚未选择可用于市场研究的当前目标"}
          </p>
          <p>
            <strong>就业：</strong>
            {strings(scope.employment).join("、") || "加载中"}
          </p>
          <p>
            <strong>接单：</strong>
            {strings(scope.freelancing).join("、") || "加载中"}
          </p>
          <p>
            <strong>产品化：</strong>
            {strings(scope.productization).join("、") || "加载中"}
          </p>
          {(["employment", "freelancing", "productization"] as const).map(
            (path) => (
              <p key={path}>
                <strong>{path} 证据能力：</strong>
                {evidenceCapabilities[path]?.coverage ===
                "conclusive_supported"
                  ? "具备受管直接信号，可在门禁满足时形成有限结论"
                  : `当前来源体系不支持判断：${String(
                      evidenceCapabilities[path]?.reason ?? "未声明原因",
                    )}`}
              </p>
            ),
          )}
        </div>
        {warningRatios.length ? (
          <div className="warning-banner" role="status">
            本月预算已达到{" "}
            {Math.round(Math.max(...warningRatios) * 100)}
            % 告警线；达到 100% 后系统会硬停止。
          </div>
        ) : null}
        <p className="audit-note">
          不自动充值；达到费用上限、官方价格改变或无法核验、余额不足、网络超时、模型异常时立即停止，不重试、不换模型。
        </p>
      </section>

      <section className="panel research-sources">
        <div className="section-heading">
          <div>
            <span className="eyebrow">Official allowlist</span>
            <h2>只访问已审查的官方来源</h2>
          </div>
          <span>{catalogSources.length} 个来源</span>
        </div>
        <div className="source-allowlist">
          {catalogSources.map((source) => {
            const access = sourceAccessById.get(String(source.id));
            return (
              <article key={String(source.id)}>
                <strong>{String(source.owner)}</strong>
                <span>{String(source.url)}</span>
                <small>{strings(source.paths).join("、")}</small>
                <small>
                  最近访问：
                  {access?.latest_attempt_status === "succeeded"
                    ? "成功"
                    : access?.latest_attempt_status === "failed"
                      ? `失败（${access.latest_attempt_error_code ?? "原因未记录"}）`
                      : "尚无"}
                  {" · "}
                  {localTime(access?.latest_attempt_at ?? null)}
                </small>
                <small>
                  最近成功快照：{localTime(access?.latest_success_at ?? null)}
                  {access?.cooling_down
                    ? ` · 下次可访问 ${localTime(access.next_allowed_at)}`
                    : " · 当前可访问"}
                </small>
              </article>
            );
          })}
        </div>
        <p className="audit-note">
          成功来源 7 天后才可再次访问；访问失败后冷却 24
          小时。首版不提供人工绕过，重建研究也不能跳过该规则。
        </p>
        {sourceAccessBlocked ? (
          <div className="warning-banner" role="status">
            当前所有来源仍在冷却中，最早可于{" "}
            {localTime(sourceAccessPolicy?.next_allowed_at ?? null)}
            再次检查（{remainingTime(sourceAccessPolicy?.remaining_seconds ?? 0)}
            ）。失败原因和历史快照仍可查看。
          </div>
        ) : sourceAccessPolicy?.blocked_source_ids.length ? (
          <div className="warning-banner" role="status">
            {sourceAccessPolicy.blocked_source_ids.length} 个来源仍在冷却中；本次只访问已到期来源，
            其余来源复用既有快照，不会重复请求站点。
          </div>
        ) : null}
      </section>

      <section className="panel research-control">
        <div className="section-heading">
          <div>
            <span className="eyebrow">Explicit controls</span>
            <h2>每一步都由你确认</h2>
          </div>
          {run ? <span className="status">{statusLabels[run.status]}</span> : null}
        </div>

        {canOfferStart ? (
          <div className="research-action">
            <label>
              当前目标与能力范围
              <select
                value={goalSelectionId}
                disabled={busy}
                onChange={(event) => setGoalSelectionId(event.target.value)}
              >
                <option value="">请选择已明确设置的变现目标</option>
                {contexts.map((context) => (
                  <option
                    key={String(context.goal_selection_id)}
                    value={String(context.goal_selection_id)}
                  >
                    {String(context.goal_kind)} · {String(context.skill_id)}@
                    {String(context.skill_version)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              DeepSeek 档案
              <select
                value={profileId}
                disabled={busy}
                onChange={(event) => setProfileId(event.target.value)}
              >
                <option value="">请选择已锁定的档案</option>
                {approvedProfiles.map((profile) => (
                  <option key={profile.id} value={profile.id}>
                    {profile.display_name} · {profile.model_id}
                  </option>
                ))}
              </select>
            </label>
            {!approvedProfiles.length ? (
              <p className="audit-note">
                尚无可用档案。请先到“设置”保存 DeepSeek 官方
                deepseek-v4-flash 档案与 API 密钥。
              </p>
            ) : null}
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={confirmSources}
                disabled={busy}
                onChange={(event) => setConfirmSources(event.target.checked)}
              />
              <span>
                <strong>确认本次访问上述官方公开来源</strong>
                <small>只保存哈希、元数据和最多 2000 字符的净化摘录。</small>
              </span>
            </label>
            <button
              className="primary-button"
              type="button"
              disabled={busy || !profileId || !confirmSources || sourceAccessBlocked}
              onClick={startSourceCheck}
            >
              检查官方市场来源
            </button>
          </div>
        ) : null}

        {!contexts.length ? (
          <div className="warning-banner" role="status">
            当前没有与受管研究目录匹配的变现目标。请先在“目标与准备度”页明确选择就业、接单或产品化目标；系统不会默认你希望变现。
          </div>
        ) : null}

        {run?.status === "synthesis_pending" ? (
          <div className="research-action">
            <p>
              已取得 {run.sources.filter((source) => source.status === "current").length}{" "}
              个可用官方来源。综合前会免费复核 DeepSeek 官方价格，并预留最坏
              ¥0.0600；实际按返回 token 记账。
            </p>
            {!externalAiEnabled ? (
              <div className="warning-banner" role="status">
                外部 AI 总开关当前关闭。请先在“诊断”页明确开启“允许外部
                AI”；系统不会绕过。
              </div>
            ) : null}
            <div className="outbound-preview" aria-label="本次外发材料预览">
              <strong>发送前最终材料预览</strong>
              <p>
                响应协议：
                {String(
                  outboundPreview.response_protocol ??
                    "limited_background_v1",
                )}
                。模型只能返回背景摘要和限制；路径状态由后端固定为
                indeterminate，内容影响固定为 no_change。
              </p>
              <p>将发送：</p>
              <ul>
                {sentDataCategories.map((category) => (
                  <li key={category}>{dataCategoryLabels[category] ?? category}</li>
                ))}
              </ul>
              <p>不会发送：</p>
              <ul>
                {excludedDataCategories.map((category) => (
                  <li key={category}>{dataCategoryLabels[category] ?? category}</li>
                ))}
              </ul>
              <p>
                以下 {outboundMaterials.length} 项材料与后端实际构造综合请求时使用同一净化列表。
              </p>
            </div>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={confirmAi}
                disabled={busy || !externalAiEnabled}
                onChange={(event) => setConfirmAi(event.target.checked)}
              />
              <span>
                <strong>确认发送净化后的最少官方摘录给 DeepSeek</strong>
                <small>
                  不发送 API 密钥、原始全文、学习记录或本地路径；30
                  天内最多一次付费综合。
                </small>
              </span>
            </label>
            <button
              className="primary-button"
              type="button"
              disabled={busy || !confirmAi || !externalAiEnabled}
              onClick={synthesize}
            >
              使用 deepseek-v4-flash 综合
            </button>
            <button
              className="text-button"
              type="button"
              disabled={busy}
              onClick={() =>
                void runAction(() => completeMarketResearchMetadataOnly(run.id))
              }
            >
              仅保存本次免费元数据检查
            </button>
          </div>
        ) : null}

        {canRecoverPreDispatch ? (
          <div className="research-action">
            <div className="warning-banner" role="alert">
              上一次操作在 DeepSeek 请求发出前因官方价格表无法解析而停止，发送、响应、token
              和费用记录均为 0。恢复只会重新进入“等待 AI 综合”，不会在此步骤调用模型。
            </div>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={confirmPreDispatchRecovery}
                disabled={busy}
                onChange={(event) =>
                  setConfirmPreDispatchRecovery(event.target.checked)
                }
              />
              <span>
                <strong>确认恢复尚未发送且费用为 0 的价格预检失败</strong>
                <small>原失败审计会保留；恢复后仍需单独确认 DeepSeek 调用。</small>
              </span>
            </label>
            <button
              className="primary-button"
              type="button"
              disabled={busy || !confirmPreDispatchRecovery}
              onClick={recoverPreDispatch}
            >
              恢复到等待综合
            </button>
          </div>
        ) : null}

        {run && outboundMaterials.length ? (
          <details
            className="research-audit outbound-materials"
            open={run.status === "synthesis_pending"}
          >
            <summary>逐项检查或删除已保存的净化摘录</summary>
            <div className="source-allowlist">
              {outboundMaterials.map((material) => {
                const sourceId = String(material.source_id);
                return (
                  <article key={sourceId}>
                    <strong>{String(material.owner)} · {sourceId}</strong>
                    <small>
                      适用路径：{strings(material.relevant_paths).join("、") || "仅背景"}
                    </small>
                    <p>{String(material.excerpt ?? "")}</p>
                    <small>
                      限制：{strings(material.limitations).join("；") || "未声明"}
                    </small>
                    <label className="checkbox-row">
                      <input
                        type="checkbox"
                        checked={redactionSourceId === sourceId}
                        disabled={busy || run.status === "synthesis_in_progress"}
                        onChange={(event) =>
                          setRedactionSourceId(event.target.checked ? sourceId : "")
                        }
                      />
                      <span>确认删除 {sourceId} 的已保存摘录</span>
                    </label>
                    <button
                      className="text-button"
                      type="button"
                      disabled={busy || redactionSourceId !== sourceId}
                      onClick={() => redactSource(sourceId)}
                    >
                      删除这项摘录
                    </button>
                  </article>
                );
              })}
            </div>
          </details>
        ) : null}

        {run?.status === "review_pending" ? (
          <div className="research-action">
            <div className="synthesis-result">
              <strong>AI 综合结果（尚未采纳）</strong>
              <pre>{JSON.stringify(run.synthesis, null, 2)}</pre>
            </div>
            <label>
              复核备注
              <textarea
                rows={4}
                maxLength={2000}
                value={reviewNote}
                disabled={busy}
                onChange={(event) => setReviewNote(event.target.value)}
              />
            </label>
            <div className="decision-actions">
              <button
                className="primary-button"
                type="button"
                disabled={busy}
                onClick={() => review("accepted")}
              >
                接受为研究记录
              </button>
              <button
                className="text-button"
                type="button"
                disabled={busy}
                onClick={() => review("rejected")}
              >
                拒绝本次综合
              </button>
            </div>
            <p className="audit-note">
              接受也不会自动修改技能包、学习计划或准备度结论；内容影响仍需独立版本和确认。
            </p>
          </div>
        ) : null}

        {run?.status === "recovery_required" ? (
          <div className="research-action">
            <div className="warning-banner" role="alert">
              上一次付费调用的租约已过期。系统没有自动重试；若请求是否收费无法确认，预算已按最坏费用保守计入。
            </div>
            <button
              className="primary-button"
              type="button"
              disabled={busy}
              onClick={() =>
                void runAction(() =>
                  reconcileMarketResearchRecovery(run.id, {
                    confirm_end: true,
                    note: "用户在本地界面确认结束遗留调用，不发起第二次模型请求。",
                  }),
                )
              }
            >
              确认结束并保留保守记账
            </button>
          </div>
        ) : null}

        {run?.status === "failed" &&
        run.failure_code &&
        invalidSynthesisFailureCodes.has(run.failure_code) ? (
          <div className="warning-banner" role="alert">
            DeepSeek 已响应，但内容没有通过受限协议校验，因此未生成、保存或开放任何可采纳的市场结论。
            审计只保留失败阶段、结构摘要、token 与费用，不保存无效响应原文。
          </div>
        ) : null}

        {run ? (
          <details className="research-audit">
            <summary>查看本次研究审计摘要</summary>
            <dl>
              <div>
                <dt>研究 ID</dt>
                <dd>{run.id}</dd>
              </div>
              <div>
                <dt>请求 / 响应模型</dt>
                <dd>
                  {run.model_id} / {run.response_model_id ?? "尚未收到可验证响应"}
                </dd>
              </div>
              <div>
                <dt>技能与能力范围</dt>
                <dd>
                  {run.skill_id}@{run.skill_version} · {run.capability_scope_id}
                </dd>
              </div>
              <div>
                <dt>当前目标</dt>
                <dd>{run.goal_kind}</dd>
              </div>
              <div>
                <dt>实际费用</dt>
                <dd>{yuan(run.actual_cost_micros)}</dd>
              </div>
              <div>
                <dt>预算计入</dt>
                <dd>{yuan(run.accounted_cost_micros)}</dd>
              </div>
              <div>
                <dt>Token 用量</dt>
                <dd>
                  输入 {run.input_tokens} / 缓存输入 {run.cached_input_tokens} /
                  输出 {run.output_tokens}
                </dd>
              </div>
              <div>
                <dt>复核状态</dt>
                <dd>{run.review_status}</dd>
              </div>
              <div>
                <dt>失败代码</dt>
                <dd>{run.failure_code ?? "无"}</dd>
              </div>
            </dl>
          </details>
        ) : null}

        {run?.synthesis && !run.synthesis_valid ? (
          <div className="warning-banner" role="alert">
            该综合结果所依赖的来源已撤回，只保留审计记录，不能继续采纳。
          </div>
        ) : null}

        <details className="research-audit">
          <summary>查看历史研究与审计事件</summary>
          <p>最近 {history.runs.length} 次研究，{history.events.length} 条事件。</p>
          <ul>
            {history.events.slice(0, 20).map((event) => (
              <li key={event.id}>
                {new Date(event.occurred_at).toLocaleString("zh-CN")} ·{" "}
                {event.event_type} · {event.run_id}
                <pre>{JSON.stringify(event.payload, null, 2)}</pre>
              </li>
            ))}
          </ul>
        </details>
      </section>
    </div>
  );
}

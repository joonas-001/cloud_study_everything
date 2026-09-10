"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { StatusMessage } from "@/components/status-message";
import type {
  OperationsOverviewResponse,
  SupportAccessGrantResponse,
  SupportCaseResponse,
} from "@/generated/api-schema";
import {
  approveSupportAccess,
  createSupportCase,
  getOperationsOverview,
  getSupportAccessRequests,
  getSupportCases,
  messageForError,
  revokeSupportAccess,
  updateOperationsControls,
} from "@/lib/api";

const categories = [
  ["product_support", "产品支持"],
  ["account_recovery", "账号恢复"],
  ["security_vulnerability", "安全漏洞"],
  ["privacy_request", "隐私请求"],
  ["content_correction", "内容纠错"],
  ["abuse_appeal", "滥用申诉"],
] as const;

export function OperationsCenter() {
  const [overview, setOverview] = useState<OperationsOverviewResponse | null>(null);
  const [cases, setCases] = useState<Array<SupportCaseResponse>>([]);
  const [grants, setGrants] = useState<Array<SupportAccessGrantResponse>>([]);
  const [category, setCategory] = useState<(typeof categories)[number][0]>("product_support");
  const [summary, setSummary] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([getOperationsOverview(), getSupportCases(), getSupportAccessRequests()])
      .then(([nextOverview, nextCases, nextGrants]) => {
        if (!active) return;
        setOverview(nextOverview);
        setCases(nextCases);
        setGrants(nextGrants);
      })
      .catch((reason: unknown) => {
        if (active) setError(messageForError(reason));
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    setStatus(null);
    try {
      await action();
    } catch (reason: unknown) {
      setError(messageForError(reason));
    } finally {
      setBusy(false);
    }
  }

  function submitCase(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void run(async () => {
      const created = await createSupportCase({ category, summary, description });
      setCases((current) => [created, ...current]);
      setSummary("");
      setDescription("");
      setStatus("支持请求已保存在当前账号范围；没有自动外发，也没有附件。");
    });
  }

  function changeControls(values: Record<string, boolean | string>, reasonCode: string) {
    void run(async () => {
      const controls = await updateOperationsControls({
        ...values,
        reason_code: reasonCode,
      });
      setOverview((current) => (current ? { ...current, controls } : current));
      setStatus("运营控制已更新并写入追加式审计。外部 AI、来源和邮件仍保持关闭。");
    });
  }

  function approve(grantId: string) {
    void run(async () => {
      const updated = await approveSupportAccess(grantId);
      setGrants((current) => current.map((item) => (item.id === grantId ? updated : item)));
      setStatus("支持访问已完成双重确认；只能在既定范围和期限内使用。");
    });
  }

  function revoke(grantId: string) {
    void run(async () => {
      const updated = await revokeSupportAccess(grantId, {
        reason_code: "user_or_operator_revoked_access",
      });
      setGrants((current) => current.map((item) => (item.id === grantId ? updated : item)));
      setStatus("访问授权已撤销。后续读取将被拒绝。");
    });
  }

  const owner = overview?.role === "owner_operator";

  return (
    <section className="panel settings-section" aria-busy={busy}>
      <header>
        <span className="eyebrow">Operations · 9E synthetic candidate</span>
        <h2>支持、安全与运营控制</h2>
        <p>
          六类问题分别分流；支持账号默认不能查看正文。普通访问需要支持人员申请和所有者批准，
          且会在到期或撤销后立即失效。当前不接真实用户，也不配置真实支持邮箱。
        </p>
      </header>

      {error ? (
        <StatusMessage tone="error" title="运营操作未完成">
          {error}
        </StatusMessage>
      ) : null}
      {status ? <StatusMessage tone="success">{status}</StatusMessage> : null}

      <div className="provider-cards operations-summary">
        <article>
          <div>
            <strong>服务状态</strong>
            <span>{overview?.controls.service_mode ?? "读取中"}</span>
          </div>
          <p>Runner 和邀请可分别急停；全站可切换只读或停服，恢复入口保留给所有者。</p>
        </article>
        <article>
          <div>
            <strong>支持承诺</strong>
            <span>中国时间工作日</span>
          </div>
          <p>10:00–18:00；普通请求 2 个工作日、安全与隐私请求 1 个工作日内首次响应。</p>
        </article>
        <article>
          <div>
            <strong>预算边界</strong>
            <span>硬上限 ¥500/月</span>
          </div>
          <p>¥250/¥400 告警；禁止自动充值与扩容。9E 新增持续费用为 0。</p>
        </article>
        <article>
          <div>
            <strong>真实用户放行</strong>
            <span>阻塞</span>
          </div>
          <p>9F 验收、专业复核、专用联系渠道和真实身份供应商仍未完成。</p>
        </article>
      </div>

      {owner && overview ? (
        <div className="operations-controls" aria-label="运营急停控制">
          <h3>所有者急停</h3>
          <div className="answer-actions">
            <button
              className="text-button"
              type="button"
              disabled={busy}
              onClick={() =>
                changeControls(
                  { invitations_enabled: !overview.controls.invitations_enabled },
                  "owner_invitation_switch",
                )
              }
            >
              邀请：{overview.controls.invitations_enabled ? "开启" : "停止"}
            </button>
            <button
              className="text-button"
              type="button"
              disabled={busy}
              onClick={() =>
                changeControls(
                  { runner_enabled: !overview.controls.runner_enabled },
                  "owner_runner_switch",
                )
              }
            >
              Runner：{overview.controls.runner_enabled ? "开启" : "停止"}
            </button>
            <button
              className="text-button"
              type="button"
              disabled={busy}
              onClick={() =>
                changeControls(
                  {
                    service_mode:
                      overview.controls.service_mode === "read_only" ? "normal" : "read_only",
                  },
                  "owner_read_only_switch",
                )
              }
            >
              {overview.controls.service_mode === "read_only" ? "退出只读" : "切换全站只读"}
            </button>
          </div>
          <small>停服操作保留在受控 API/手册中，避免页面误触；所有变更均需原因码。</small>
        </div>
      ) : null}

      <form className="settings-form support-form" onSubmit={submitCase}>
        <h3>新建最少化支持请求</h3>
        <div className="settings-form-grid">
          <label>
            分流类别
            <select
              value={category}
              disabled={busy}
              onChange={(event) =>
                setCategory(event.target.value as (typeof categories)[number][0])
              }
            >
              {categories.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            摘要
            <input
              value={summary}
              minLength={3}
              maxLength={160}
              required
              disabled={busy}
              onChange={(event) => setSummary(event.target.value)}
            />
          </label>
        </div>
        <label>
          必要说明
          <textarea
            value={description}
            minLength={3}
            maxLength={4000}
            required
            disabled={busy}
            onChange={(event) => setDescription(event.target.value)}
          />
          <small className="field-hint">
            不要填写身份证、合同、账单、银行材料、完整日志、数据库、密钥或 token；附件已关闭。
          </small>
        </label>
        <button className="primary-button" type="submit" disabled={busy}>
          保存本地支持请求
        </button>
      </form>

      {cases.length ? (
        <div className="saved-profiles">
          <h3>我的支持请求</h3>
          {cases.map((item) => (
            <article key={item.id}>
              <div>
                <strong>{item.summary}</strong>
                <span>{item.status}</span>
              </div>
              <p>{item.description}</p>
              <small>
                {item.category} · {new Date(item.created_at).toLocaleString()}
              </small>
            </article>
          ))}
        </div>
      ) : null}

      {grants.length ? (
        <div className="saved-profiles support-grants">
          <h3>访问授权与通知</h3>
          {grants.map((grant) => (
            <article key={grant.id}>
              <div>
                <strong>{grant.reason_code}</strong>
                <span>{grant.status}</span>
              </div>
              <p>
                范围 {grant.scope} · 到期 {new Date(grant.expires_at).toLocaleString()}
                {grant.post_notice_pending ? " · 紧急访问事后通知待完成" : ""}
              </p>
              <div className="answer-actions">
                {owner && grant.status === "requested" ? (
                  <button className="text-button" type="button" onClick={() => approve(grant.id)}>
                    批准最小访问
                  </button>
                ) : null}
                {grant.status === "requested" || grant.status === "active" ? (
                  <button className="text-button" type="button" onClick={() => revoke(grant.id)}>
                    撤销访问
                  </button>
                ) : null}
              </div>
            </article>
          ))}
        </div>
      ) : null}
    </section>
  );
}

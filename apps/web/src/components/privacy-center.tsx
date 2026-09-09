"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { StatusMessage } from "@/components/status-message";
import type {
  PrivacyAccessReportResponse,
  PrivacyOverviewResponse,
} from "@/generated/api-schema";
import {
  acceptPrivacyPolicies,
  cancelPrivacyDeletionJob,
  correctPrivacyData,
  createPrivacyDeletionJob,
  createPrivacyExport,
  getPrivacyAccessReport,
  getPrivacyOverview,
  messageForError,
  updatePrivacyChoices,
} from "@/lib/api";

export function PrivacyCenter() {
  const [overview, setOverview] = useState<PrivacyOverviewResponse | null>(null);
  const [access, setAccess] = useState<PrivacyAccessReportResponse | null>(null);
  const [timeoutMinutes, setTimeoutMinutes] = useState(120);
  const [deletionConfirmed, setDeletionConfirmed] = useState(false);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getPrivacyOverview()
      .then((value) => {
        if (active) setOverview(value);
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

  function acceptRequiredPolicies() {
    void run(async () => {
      const required =
        overview?.documents
          .filter((document) => document.required && !document.accepted)
          .map((document) => document.document_type) ?? [];
      if (!required.length) {
        setStatus("当前候选政策版本已经确认。");
        return;
      }
      setOverview(await acceptPrivacyPolicies({ document_types: required }));
      setStatus("已记录当前候选版本和确认时间。真实内测仍需专业复核与 9G 授权。");
    });
  }

  function changeChoice(purpose: string, enabled: boolean) {
    void run(async () => {
      setOverview(await updatePrivacyChoices({ choices: { [purpose]: enabled } }));
      setStatus("分项选择已保存；9D 不会据此启用任何真实外部能力。");
    });
  }

  function loadAccessReport() {
    void run(async () => {
      setAccess(await getPrivacyAccessReport());
      setStatus("已生成仅属于当前账号的数据分类与逐表数量。");
    });
  }

  function saveCorrection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void run(async () => {
      setOverview(
        await correctPrivacyData({
          inactivity_timeout_minutes: timeoutMinutes,
          choices: {},
        }),
      );
      setStatus("无操作时限已更正，并记录了不含原值的完成摘要。");
    });
  }

  function downloadExport() {
    void run(async () => {
      const payload = await createPrivacyExport({ confirm_sensitive_data: true });
      const blob = new Blob([JSON.stringify(payload, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `cloud-study-export-${payload.generated_at.slice(0, 10)}.json`;
      link.click();
      URL.revokeObjectURL(url);
      setStatus(`全量导出已生成，SHA-256：${payload.content_sha256}`);
    });
  }

  function requestDeletion() {
    void run(async () => {
      const job = await createPrivacyDeletionJob();
      setOverview((current) =>
        current ? { ...current, deletion_job: job } : current,
      );
      setDeletionConfirmed(false);
      setStatus("账号已进入 7 天删除等待期，会话已撤销。重新登录后可在到期前撤销。");
    });
  }

  function cancelDeletion() {
    void run(async () => {
      const job = await cancelPrivacyDeletionJob();
      setOverview((current) =>
        current ? { ...current, deletion_job: job } : current,
      );
      setStatus("删除作业已撤销，账号恢复为可用状态。");
    });
  }

  return (
    <section className="panel settings-section" aria-busy={busy}>
      <header>
        <span className="eyebrow">Privacy rights · 9D candidate</span>
        <h2>隐私权利与数据生命周期</h2>
        <p>
          这里的政策和流程只用于合成多用户候选验证。专业复核、专用隐私联系渠道、真实身份和
          9G 授权仍未完成。
        </p>
      </header>

      {error ? (
        <StatusMessage tone="error" title="隐私操作未完成">
          {error}
        </StatusMessage>
      ) : null}
      {status ? <StatusMessage tone="success">{status}</StatusMessage> : null}

      <div className="provider-cards">
        {overview?.documents.map((document) => (
          <article key={document.document_type}>
            <div>
              <strong>{document.title}</strong>
              <span>{document.accepted ? "已确认" : document.required ? "待确认" : "仅告知"}</span>
            </div>
            <p>{document.summary}</p>
            <small>
              版本 {document.version} · {document.review_status}
            </small>
            <details className="privacy-document">
              <summary>查看完整候选文本</summary>
              <pre>{document.content_markdown}</pre>
            </details>
          </article>
        ))}
      </div>
      <button className="primary-button" type="button" disabled={busy} onClick={acceptRequiredPolicies}>
        确认当前必要候选版本
      </button>

      <div className="preference-options">
        {overview?.choices.map((choice) => (
          <label className="checkbox-row" key={choice.purpose}>
            <input
              type="checkbox"
              checked={choice.enabled}
              disabled={busy}
              onChange={(event) => changeChoice(choice.purpose, event.target.checked)}
            />
            <span>
              <strong>{choice.label}</strong>
              <small>{choice.effective_reason}</small>
            </span>
          </label>
        ))}
      </div>

      <div className="answer-actions">
        <button className="text-button" type="button" disabled={busy} onClick={loadAccessReport}>
          查看我的数据范围
        </button>
        <button className="text-button" type="button" disabled={busy} onClick={downloadExport}>
          确认并导出全部数据
        </button>
      </div>
      {access ? (
        <div className="saved-profiles">
          <h3>当前账号数据摘要</h3>
          <p>{access.scope_note}</p>
          <small>
            {Object.values(access.table_counts).reduce<number>(
              (total, value) => total + (typeof value === "number" ? value : 0),
              0,
            )} 条用户归属记录 · 生成于 {new Date(access.generated_at).toLocaleString()}
          </small>
        </div>
      ) : null}

      <form className="settings-form" onSubmit={saveCorrection}>
        <label>
          更正无操作时限（分钟）
          <input
            type="number"
            min={1}
            max={1440}
            value={timeoutMinutes}
            disabled={busy}
            onChange={(event) => setTimeoutMinutes(Number(event.target.value))}
          />
        </label>
        <button className="text-button" type="submit" disabled={busy}>
          保存更正
        </button>
      </form>

      <div className="settings-form">
        <h3>删除账号与数据</h3>
        {overview?.deletion_job?.status === "waiting" ? (
          <>
            <p>
              删除将在 {new Date(overview.deletion_job.execute_after).toLocaleString()} 后执行；到期前可撤销。
            </p>
            <button className="text-button" type="button" disabled={busy} onClick={cancelDeletion}>
              撤销删除
            </button>
          </>
        ) : (
          <>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={deletionConfirmed}
                disabled={busy}
                onChange={(event) => setDeletionConfirmed(event.target.checked)}
              />
              我理解请求后全部会话立即撤销，7 天后清除业务正文，备份最长 28 天自然过期。
            </label>
            <button
              className="text-button"
              type="button"
              disabled={busy || !deletionConfirmed}
              onClick={requestDeletion}
            >
              请求删除账号
            </button>
          </>
        )}
      </div>
    </section>
  );
}

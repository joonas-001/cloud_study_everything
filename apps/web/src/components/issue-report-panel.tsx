"use client";

import { useState } from "react";

import { StatusMessage } from "@/components/status-message";
import type {
  IssueReportPreviewRequest,
  IssueReportPreviewResponse,
} from "@/generated/api-schema";
import { messageForError, previewIssueReport } from "@/lib/api";

type OptionalField = IssueReportPreviewRequest["included_optional_fields"][number];

const OPTIONAL_FIELD_LABELS: Record<OptionalField, string> = {
  page_route: "页面路由",
  operation_type: "受管操作类型",
  skill_version: "精确技能版本",
  request_audit_id: "请求审计 UUID",
  reason_code: "原因码",
  event_names: "受管事件名称",
  runner_details: "Runner 协议与运行时",
};
const DEFAULT_OPTIONAL_FIELDS: Array<OptionalField> = [
  "page_route",
  "operation_type",
  "skill_version",
  "runner_details",
];

export function IssueReportPanel() {
  const [reportType, setReportType] = useState<"bug" | "feature" | "content">("bug");
  const [pageRoute, setPageRoute] = useState("/settings");
  const [operationType, setOperationType] = useState("page_load");
  const [skillVersion, setSkillVersion] = useState("algorithm@0.3.0");
  const [auditId, setAuditId] = useState("");
  const [reasonCode, setReasonCode] = useState("");
  const [eventName, setEventName] = useState("");
  const [included, setIncluded] = useState<Array<OptionalField>>(DEFAULT_OPTIONAL_FIELDS);
  const [preview, setPreview] = useState<IssueReportPreviewResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  function payloadFor(nextIncluded: Array<OptionalField>): IssueReportPreviewRequest {
    const has = (field: OptionalField) => nextIncluded.includes(field);
    return {
      report_type: reportType,
      included_optional_fields: nextIncluded,
      page_route: has("page_route") ? pageRoute : null,
      operation_type: has("operation_type") ? operationType : null,
      skill_version: has("skill_version") ? skillVersion : null,
      request_audit_id: has("request_audit_id") && auditId ? auditId : null,
      reason_code: has("reason_code") && reasonCode ? reasonCode : null,
      event_names: has("event_names") && eventName ? [eventName] : [],
    };
  }

  async function generate(nextIncluded = included) {
    setBusy(true);
    setError(null);
    setStatus(null);
    setCopied(false);
    try {
      setPreview(await previewIssueReport(payloadFor(nextIncluded)));
    } catch (reason: unknown) {
      setPreview(null);
      setError(messageForError(reason));
    } finally {
      setBusy(false);
    }
  }

  function invalidate() {
    setPreview(null);
    setCopied(false);
    setStatus(null);
  }

  function toggleOptional(field: OptionalField, checked: boolean) {
    const next = checked
      ? [...included, field]
      : included.filter((item) => item !== field);
    setIncluded(next);
    if (preview) {
      void generate(next);
    } else {
      setCopied(false);
    }
  }

  async function copyPreview() {
    if (!preview) {
      return;
    }
    setError(null);
    setStatus(null);
    try {
      await navigator.clipboard.writeText(preview.rendered_text);
      setCopied(true);
      setStatus("脱敏诊断已复制。打开 GitHub 前请再检查一次剪贴板内容。");
    } catch {
      setCopied(false);
      setError("浏览器未允许写入剪贴板。诊断仍保留在本地预览中，可手动选择复制。");
    }
  }

  return (
    <section className="panel settings-section issue-report-panel">
      <header>
        <span className="eyebrow">System status · Issue reporting</span>
        <h2>报告问题</h2>
        <p>
          本地生成允许列表诊断，完整预览并删除可选字段后再复制。系统不会自动提交、评论或上传附件。
        </p>
      </header>

      {error ? (
        <StatusMessage tone="error" title="未生成或复制诊断">
          {error}
        </StatusMessage>
      ) : null}
      {status ? <StatusMessage tone="success">{status}</StatusMessage> : null}

      <div className="issue-report-boundary" role="note">
        <strong>公开 Issue 禁止敏感正文</strong>
        <p>
          不得包含答案、代码、证据正文、凭据、身份、邮箱、私有地址、本地路径、完整日志、数据库、AI
          或市场正文、收入和账单。安全问题请走私密报告入口。
        </p>
      </div>

      <div className="settings-form issue-report-form" aria-busy={busy}>
        <div className="form-grid">
          <label>
            报告类型
            <select
              value={reportType}
              disabled={busy}
              onChange={(event) => {
                setReportType(event.target.value as typeof reportType);
                invalidate();
              }}
            >
              <option value="bug">缺陷报告</option>
              <option value="feature">功能或改进</option>
              <option value="content">内容或证据问题</option>
            </select>
          </label>
          <label>
            页面路由
            <select
              value={pageRoute}
              disabled={busy || !included.includes("page_route")}
              onChange={(event) => {
                setPageRoute(event.target.value);
                invalidate();
              }}
            >
              {["/", "/diagnostic", "/learning", "/evidence", "/goals", "/inbox", "/settings"].map(
                (route) => (
                  <option key={route} value={route}>
                    {route}
                  </option>
                ),
              )}
            </select>
          </label>
          <label>
            操作类型
            <select
              value={operationType}
              disabled={busy || !included.includes("operation_type")}
              onChange={(event) => {
                setOperationType(event.target.value);
                invalidate();
              }}
            >
              <option value="page_load">页面加载</option>
              <option value="save_settings">保存设置</option>
              <option value="diagnostic">诊断</option>
              <option value="planning">规划</option>
              <option value="learning">学习执行</option>
              <option value="evidence">证据</option>
              <option value="runner">Runner</option>
              <option value="export">导出</option>
              <option value="notification">通知</option>
              <option value="managed_other">其他受管操作</option>
            </select>
          </label>
          <label>
            精确技能版本
            <select
              value={skillVersion}
              disabled={busy || !included.includes("skill_version")}
              onChange={(event) => {
                setSkillVersion(event.target.value);
                invalidate();
              }}
            >
              {["algorithm@0.3.0", "algorithm@0.2.2", "algorithm@0.2.1", "algorithm@0.2.0", "algorithm@0.1.0"].map(
                (version) => (
                  <option key={version} value={version}>
                    {version}
                  </option>
                ),
              )}
            </select>
          </label>
          <label>
            请求审计 UUID（选填）
            <input
              value={auditId}
              maxLength={36}
              disabled={busy || !included.includes("request_audit_id")}
              placeholder="xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx"
              onChange={(event) => {
                setAuditId(event.target.value.trim());
                invalidate();
              }}
            />
          </label>
          <label>
            原因码（选填）
            <input
              value={reasonCode}
              maxLength={64}
              pattern="[a-z][a-z0-9_]{0,63}"
              disabled={busy || !included.includes("reason_code")}
              placeholder="runner_unavailable"
              onChange={(event) => {
                setReasonCode(event.target.value.trim());
                invalidate();
              }}
            />
          </label>
          <label>
            受管事件（选填）
            <select
              value={eventName}
              disabled={busy || !included.includes("event_names")}
              onChange={(event) => {
                setEventName(event.target.value);
                invalidate();
              }}
            >
              <option value="">不加入事件</option>
              <option value="api_request_failed">api_request_failed</option>
              <option value="contract_validation_failed">contract_validation_failed</option>
              <option value="database_revision_mismatch">database_revision_mismatch</option>
              <option value="learning_action_failed">learning_action_failed</option>
              <option value="runner_protocol_invalid">runner_protocol_invalid</option>
              <option value="runner_unavailable">runner_unavailable</option>
              <option value="source_review_pending">source_review_pending</option>
            </select>
          </label>
        </div>

        <fieldset className="issue-field-selector">
          <legend>可选字段：取消勾选即可从下一份预览删除</legend>
          {Object.entries(OPTIONAL_FIELD_LABELS).map(([key, label]) => (
            <label className="checkbox-row" key={key}>
              <input
                type="checkbox"
                checked={included.includes(key as OptionalField)}
                disabled={busy}
                onChange={(event) =>
                  toggleOptional(key as OptionalField, event.target.checked)
                }
              />
              <span>{label}</span>
            </label>
          ))}
        </fieldset>

        <button
          className="primary-button"
          type="button"
          disabled={busy}
          onClick={() => void generate()}
        >
          {busy ? "正在生成…" : "生成本地脱敏预览"}
        </button>
      </div>

      {preview ? (
        <div className="issue-report-preview">
          <div className="section-heading-row">
            <div>
              <span className="eyebrow">Preview only</span>
              <h3>将复制的完整诊断</h3>
            </div>
            <span className="status-chip status-chip--neutral">
              {preview.fields.length} 个允许列表字段
            </span>
          </div>
          <textarea
            aria-label="脱敏诊断完整预览"
            readOnly
            rows={Math.min(18, preview.rendered_text.split("\n").length + 1)}
            value={preview.rendered_text}
          />
          <p className="field-hint">{preview.privacy_notice}</p>
          <div className="answer-actions">
            <button
              className="primary-button"
              type="button"
              disabled={busy}
              onClick={() => void copyPreview()}
            >
              复制脱敏诊断
            </button>
            {copied ? (
              <a
                className="secondary-link"
                href={preview.submission_url}
                target="_blank"
                rel="noreferrer"
              >
                由我打开 GitHub 并检查
              </a>
            ) : (
              <button className="text-button" type="button" disabled>
                由我打开 GitHub 并检查
              </button>
            )}
          </div>
          {!copied ? <small>先复制并检查诊断，GitHub 入口才会启用。</small> : null}
        </div>
      ) : null}
    </section>
  );
}

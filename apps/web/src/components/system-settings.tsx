"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import type {
  AiProviderProfileResponse,
  AiProviderResponse,
  NotificationPreferenceResponse,
} from "@/generated/api-schema";
import {
  createAiProviderProfile,
  getAiProviderProfiles,
  getAiProviders,
  getNotificationPreferences,
  messageForError,
  sendTestEmail,
  updateNotificationPreferences,
} from "@/lib/api";

type EmailForm = {
  emailEnabled: boolean;
  emailActionRequired: boolean;
  emailWarning: boolean;
  emailDelayMinutes: number;
  recipientEmail: string;
  senderEmail: string;
  smtpHost: string;
  smtpPort: number;
  smtpUsername: string;
  smtpSecurity: "starttls" | "ssl";
  smtpPassword: string;
};

const emptyEmailForm: EmailForm = {
  emailEnabled: false,
  emailActionRequired: false,
  emailWarning: false,
  emailDelayMinutes: 10,
  recipientEmail: "",
  senderEmail: "",
  smtpHost: "",
  smtpPort: 587,
  smtpUsername: "",
  smtpSecurity: "starttls",
  smtpPassword: "",
};

export function SystemSettings() {
  const [preferences, setPreferences] =
    useState<NotificationPreferenceResponse | null>(null);
  const [providers, setProviders] = useState<Array<AiProviderResponse>>([]);
  const [profiles, setProfiles] = useState<
    Array<AiProviderProfileResponse>
  >([]);
  const [emailForm, setEmailForm] = useState<EmailForm>(emptyEmailForm);
  const [providerId, setProviderId] = useState("local-deterministic");
  const [profileName, setProfileName] = useState("本地规划预览");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([
      getNotificationPreferences(),
      getAiProviders(),
      getAiProviderProfiles(),
    ])
      .then(([nextPreferences, nextProviders, nextProfiles]) => {
        if (!active) {
          return;
        }
        setPreferences(nextPreferences);
        setProviders(nextProviders);
        setProfiles(nextProfiles);
        setEmailForm({
          emailEnabled: nextPreferences.email_enabled,
          emailActionRequired: nextPreferences.email_action_required,
          emailWarning: nextPreferences.email_warning,
          emailDelayMinutes: nextPreferences.email_delay_minutes,
          recipientEmail: nextPreferences.recipient_email ?? "",
          senderEmail: nextPreferences.sender_email ?? "",
          smtpHost: nextPreferences.smtp_host ?? "",
          smtpPort: nextPreferences.smtp_port ?? 587,
          smtpUsername: nextPreferences.smtp_username ?? "",
          smtpSecurity: nextPreferences.smtp_security,
          smtpPassword: "",
        });
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

  function saveEmail(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void run(async () => {
      const updated = await updateNotificationPreferences({
        email_enabled: emailForm.emailEnabled,
        email_action_required: emailForm.emailActionRequired,
        email_warning: emailForm.emailWarning,
        email_delay_minutes: emailForm.emailDelayMinutes,
        recipient_email: emailForm.recipientEmail || null,
        sender_email: emailForm.senderEmail || null,
        smtp_host: emailForm.smtpHost || null,
        smtp_port: emailForm.smtpPort || null,
        smtp_username: emailForm.smtpUsername || null,
        smtp_security: emailForm.smtpSecurity,
        smtp_password: emailForm.smtpPassword || null,
      });
      setPreferences(updated);
      setEmailForm((current) => ({ ...current, smtpPassword: "" }));
      setStatus("通知与邮件偏好已保存。SMTP 密码不会返回到页面。");
    });
  }

  function testEmail() {
    void run(async () => {
      const notification = await sendTestEmail();
      setStatus(
        notification.email_status === "sent"
          ? "测试邮件已发送。"
          : `测试邮件状态：${notification.email_status ?? "未进入邮件队列"}`,
      );
    });
  }

  function changeProvider(nextProviderId: string) {
    setProviderId(nextProviderId);
    const provider = providers.find((item) => item.id === nextProviderId);
    setBaseUrl(provider?.default_base_url ?? "");
    setProfileName(provider?.display_name ?? "");
    setApiKey("");
  }

  function saveProviderProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void run(async () => {
      const created = await createAiProviderProfile({
        provider_id: providerId,
        display_name: profileName,
        base_url: baseUrl || null,
        api_key: apiKey || null,
        enabled: true,
      });
      setProfiles((current) => [...current, created]);
      setApiKey("");
      setStatus(
        created.executable
          ? "本地供应商档案已创建。"
          : "真实供应商档案已保存，但接口仍被禁用，不会产生 API 请求。",
      );
    });
  }

  return (
    <div className="settings-layout">
      {error ? (
        <div className="error-banner" role="alert">
          <strong>设置未保存</strong>
          <span>{error}</span>
        </div>
      ) : null}
      {status ? (
        <div className="success-banner" role="status">
          {status}
        </div>
      ) : null}

      <section className="panel settings-section">
        <header>
          <span className="eyebrow">Notification preferences</span>
          <h2>站内通知与可选邮件</h2>
          <p>
            站内通知始终保留。必要邮件立即发送；需要处理和异常警告按偏好延迟，若提前在站内阅读则取消邮件。
          </p>
        </header>
        <form className="settings-form" onSubmit={saveEmail}>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={emailForm.emailEnabled}
              disabled={busy}
              onChange={(event) =>
                setEmailForm({
                  ...emailForm,
                  emailEnabled: event.target.checked,
                })
              }
            />
            <span>
              <strong>启用真实邮件通道</strong>
              <small>只在网站运行时处理，不创建后台常驻服务。</small>
            </span>
          </label>
          <div className="form-grid">
            <label>
              收件邮箱
              <input
                type="email"
                value={emailForm.recipientEmail}
                disabled={busy}
                onChange={(event) =>
                  setEmailForm({
                    ...emailForm,
                    recipientEmail: event.target.value,
                  })
                }
              />
            </label>
            <label>
              发件邮箱
              <input
                type="email"
                value={emailForm.senderEmail}
                disabled={busy}
                onChange={(event) =>
                  setEmailForm({
                    ...emailForm,
                    senderEmail: event.target.value,
                  })
                }
              />
            </label>
            <label>
              SMTP 主机
              <input
                value={emailForm.smtpHost}
                disabled={busy}
                onChange={(event) =>
                  setEmailForm({ ...emailForm, smtpHost: event.target.value })
                }
              />
            </label>
            <label>
              SMTP 端口
              <input
                type="number"
                min={1}
                max={65535}
                value={emailForm.smtpPort}
                disabled={busy}
                onChange={(event) =>
                  setEmailForm({
                    ...emailForm,
                    smtpPort: Number(event.target.value),
                  })
                }
              />
            </label>
            <label>
              SMTP 用户名
              <input
                value={emailForm.smtpUsername}
                disabled={busy}
                onChange={(event) =>
                  setEmailForm({
                    ...emailForm,
                    smtpUsername: event.target.value,
                  })
                }
              />
            </label>
            <label>
              连接安全
              <select
                value={emailForm.smtpSecurity}
                disabled={busy}
                onChange={(event) =>
                  setEmailForm({
                    ...emailForm,
                    smtpSecurity: event.target.value as "starttls" | "ssl",
                  })
                }
              >
                <option value="starttls">STARTTLS</option>
                <option value="ssl">SSL/TLS</option>
              </select>
            </label>
            <label>
              SMTP 密码或应用专用密码
              <input
                type="password"
                value={emailForm.smtpPassword}
                disabled={busy}
                placeholder={
                  preferences?.credential_reference
                    ? "已保存；留空表示不替换"
                    : "保存在 Windows 凭据管理器"
                }
                onChange={(event) =>
                  setEmailForm({
                    ...emailForm,
                    smtpPassword: event.target.value,
                  })
                }
              />
            </label>
            <label>
              延迟分钟
              <input
                type="number"
                min={0}
                max={1440}
                value={emailForm.emailDelayMinutes}
                disabled={busy}
                onChange={(event) =>
                  setEmailForm({
                    ...emailForm,
                    emailDelayMinutes: Number(event.target.value),
                  })
                }
              />
            </label>
          </div>
          <div className="preference-options">
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={emailForm.emailActionRequired}
                disabled={busy}
                onChange={(event) =>
                  setEmailForm({
                    ...emailForm,
                    emailActionRequired: event.target.checked,
                  })
                }
              />
              需要处理的通知可以发邮件
            </label>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={emailForm.emailWarning}
                disabled={busy}
                onChange={(event) =>
                  setEmailForm({
                    ...emailForm,
                    emailWarning: event.target.checked,
                  })
                }
              />
              异常警告可以发邮件
            </label>
          </div>
          <div className="answer-actions">
            <button className="primary-button" type="submit" disabled={busy}>
              保存邮件设置
            </button>
            <button
              className="text-button"
              type="button"
              disabled={busy || !preferences?.email_enabled}
              onClick={testEmail}
            >
              发送最小测试邮件
            </button>
          </div>
        </form>
      </section>

      <section className="panel settings-section">
        <header>
          <span className="eyebrow">Provider profiles</span>
          <h2>AI 供应商档案</h2>
          <p>
            配置方式借鉴 CC Switch 的档案管理，但每家供应商保持独立适配器。当前只有本地确定性供应商可执行。
          </p>
        </header>

        <div className="provider-cards">
          {providers.map((provider) => (
            <article key={provider.id}>
              <div>
                <strong>{provider.display_name}</strong>
                <span>{provider.executable ? "可执行" : "仅接口"}</span>
              </div>
              <p>{provider.status_note}</p>
              <small>
                {provider.models.length
                  ? `模型：${provider.models.join("、")}`
                  : "首批模型尚未确认"}
              </small>
            </article>
          ))}
        </div>

        <form className="settings-form provider-form" onSubmit={saveProviderProfile}>
          <div className="form-grid">
            <label>
              供应商
              <select
                value={providerId}
                disabled={busy}
                onChange={(event) => changeProvider(event.target.value)}
              >
                {providers.map((provider) => (
                  <option key={provider.id} value={provider.id}>
                    {provider.display_name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              档案名称
              <input
                value={profileName}
                disabled={busy}
                onChange={(event) => setProfileName(event.target.value)}
              />
            </label>
            <label>
              Base URL
              <input
                value={baseUrl}
                disabled={busy}
                onChange={(event) => setBaseUrl(event.target.value)}
              />
            </label>
            <label>
              API 密钥
              <input
                type="password"
                value={apiKey}
                disabled={busy || providerId === "local-deterministic"}
                placeholder="保存到 Windows 凭据管理器"
                onChange={(event) => setApiKey(event.target.value)}
              />
            </label>
          </div>
          <button className="primary-button" type="submit" disabled={busy}>
            保存供应商档案
          </button>
        </form>

        {profiles.length ? (
          <div className="saved-profiles">
            <h3>已保存档案</h3>
            {profiles.map((profile) => (
              <article key={profile.id}>
                <div>
                  <strong>{profile.display_name}</strong>
                  <span>{profile.provider_id}</span>
                </div>
                <p>{profile.status_note}</p>
                <small>
                  凭据：
                  {profile.credential_reference ? "已保存引用" : "不需要或未配置"}
                </small>
              </article>
            ))}
          </div>
        ) : null}
      </section>
    </div>
  );
}

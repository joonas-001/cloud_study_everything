"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import type {
  DiagnosticAnswerResponse,
  DiagnosticSessionResponse,
  PrivacySettingsResponse,
} from "@/generated/api-schema";
import {
  correctDiagnosticAnswer,
  createDiagnosticSession,
  endDiagnosticSession,
  getActiveDiagnosticSession,
  getPrivacySettings,
  messageForError,
  submitDiagnosticAnswer,
  updatePrivacySettings,
} from "@/lib/api";

const SKILL_ID = "algorithm";
const SKILL_VERSION = "0.1.0";

type ResponseKind = "answered" | "skipped" | "uncertain";

function responseLabel(answer: DiagnosticAnswerResponse): string {
  if (answer.response_kind === "skipped") {
    return "已跳过";
  }
  if (answer.response_kind === "uncertain") {
    return "不确定";
  }
  return answer.content ?? "已回答";
}

export function DiagnosticInterview() {
  const [privacy, setPrivacy] = useState<PrivacySettingsResponse | null>(null);
  const [session, setSession] = useState<DiagnosticSessionResponse | null>(null);
  const [answer, setAnswer] = useState("");
  const [correction, setCorrection] = useState<DiagnosticAnswerResponse | null>(
    null,
  );
  const [correctionKind, setCorrectionKind] =
    useState<ResponseKind>("answered");
  const [correctionText, setCorrectionText] = useState("");
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([
      getPrivacySettings(),
      getActiveDiagnosticSession(SKILL_ID, SKILL_VERSION),
    ])
      .then(([nextPrivacy, nextSession]) => {
        if (active) {
          setPrivacy(nextPrivacy);
          setSession(nextSession);
        }
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
    try {
      await action();
    } catch (reason: unknown) {
      setError(messageForError(reason));
    } finally {
      setBusy(false);
    }
  }

  function startSession() {
    void run(async () => {
      const created = await createDiagnosticSession({
        skill_id: SKILL_ID,
        skill_version: SKILL_VERSION,
        preview: true,
        provider_id: "local-deterministic",
        model_id: "diagnostic-v1",
        credential_reference: null,
        external_ai_consent: false,
      });
      setSession(created);
    });
  }

  function toggleExternalAi(enabled: boolean) {
    void run(async () => {
      const updated = await updatePrivacySettings({
        external_ai_enabled: enabled,
      });
      setPrivacy(updated);
      setSession((current) =>
        current ? { ...current, external_ai_enabled: enabled } : current,
      );
    });
  }

  function submit(kind: ResponseKind) {
    if (!session?.current_question) {
      return;
    }
    void run(async () => {
      const updated = await submitDiagnosticAnswer(session.id, {
        question_id: session.current_question!.id,
        response_kind: kind,
        content: kind === "answered" ? answer : null,
      });
      setSession(updated);
      setAnswer("");
    });
  }

  function beginCorrection(item: DiagnosticAnswerResponse) {
    setCorrection(item);
    setCorrectionKind(item.response_kind);
    setCorrectionText(item.content ?? "");
  }

  function saveCorrection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !correction) {
      return;
    }
    void run(async () => {
      const updated = await correctDiagnosticAnswer(
        session.id,
        correction.question_id,
        {
          response_kind: correctionKind,
          content: correctionKind === "answered" ? correctionText : null,
        },
      );
      setSession(updated);
      setCorrection(null);
      setCorrectionText("");
    });
  }

  function endSession() {
    if (!session) {
      return;
    }
    void run(async () => {
      setSession(await endDiagnosticSession(session.id));
    });
  }

  if (busy && !privacy && !session) {
    return (
      <section className="panel loading-panel" aria-live="polite">
        <span className="loading-dot" aria-hidden="true" />
        正在连接本地学习引擎……
      </section>
    );
  }

  return (
    <div className="diagnostic-layout">
      <aside className="control-rail" aria-label="诊断配置">
        <div className="eyebrow">算法 · 0.1.0</div>
        <h2>诊断预览</h2>
        <p className="muted">
          当前技能包仍为草稿。本次结果仅用于验证访谈流程，不会生成正式学习计划或掌握结论。
        </p>

        <dl className="facts">
          <div>
            <dt>运行方式</dt>
            <dd>本地确定性</dd>
          </div>
          <div>
            <dt>模型锁定</dt>
            <dd>diagnostic-v1</dd>
          </div>
          <div>
            <dt>超时规则</dt>
            <dd>{privacy?.inactivity_timeout_minutes ?? 120} 分钟无操作</dd>
          </div>
        </dl>

        <div className="privacy-setting">
          <div>
            <strong>允许外部 AI</strong>
            <p>全局第一层开关，默认关闭。此预览即使开启也不会发送数据。</p>
          </div>
          <button
            className="switch"
            type="button"
            role="switch"
            aria-checked={privacy?.external_ai_enabled ?? false}
            aria-label="允许外部 AI"
            disabled={busy || !privacy}
            onClick={() =>
              toggleExternalAi(!(privacy?.external_ai_enabled ?? false))
            }
          >
            <span />
          </button>
        </div>
      </aside>

      <section className="panel interview-panel" aria-live="polite">
        {error ? (
          <div className="error-banner" role="alert">
            <strong>暂时无法继续</strong>
            <span>{error}</span>
          </div>
        ) : null}

        {!session ? (
          <div className="empty-state">
            <span className="step-mark">01</span>
            <h2>从真实基础开始</h2>
            <p>
              系统会说明每个问题的原因，并根据回答选择后续问题。你可以跳过、标记不确定，也可以随时修正。
            </p>
            <button
              className="primary-button"
              type="button"
              disabled={busy}
              onClick={startSession}
            >
              开始本地诊断预览
            </button>
          </div>
        ) : (
          <>
            <header className="session-header">
              <div>
                <span className="preview-badge">草稿预览 · 不外发</span>
                <h2>
                  {session.status === "active" ? "基础诊断" : "本次诊断已结束"}
                </h2>
              </div>
              <span className="answer-count">
                已记录 {session.answers.filter((item) => item.on_current_path).length} 项
              </span>
            </header>

            {session.status === "active" && session.current_question ? (
              <div className="question-block">
                <p className="question-reason">
                  <span>为什么问</span>
                  {session.current_question.reason}
                </p>
                <h3>{session.current_question.prompt}</h3>
                {session.current_question.response_type === "code_text" ? (
                  <p className="code-warning">
                    粘贴的代码只会作为不可信文本保存；系统不会执行它。
                  </p>
                ) : null}
                <label className="answer-label" htmlFor="diagnostic-answer">
                  你的回答
                </label>
                <textarea
                  id="diagnostic-answer"
                  value={answer}
                  disabled={busy}
                  placeholder="按你的实际情况回答即可；不知道时可以选择“不确定”。"
                  onChange={(event) => setAnswer(event.target.value)}
                />
                <div className="answer-actions">
                  <button
                    className="primary-button"
                    type="button"
                    disabled={busy || answer.trim().length === 0}
                    onClick={() => submit("answered")}
                  >
                    保存并继续
                  </button>
                  <button
                    className="text-button"
                    type="button"
                    disabled={busy}
                    onClick={() => submit("uncertain")}
                  >
                    不确定
                  </button>
                  <button
                    className="text-button"
                    type="button"
                    disabled={busy}
                    onClick={() => submit("skipped")}
                  >
                    跳过
                  </button>
                </div>
              </div>
            ) : null}

            {session.status === "active" && session.ready_to_end ? (
              <div className="completion-card">
                <span className="step-mark">✓</span>
                <h3>预览问题已完成</h3>
                <p>
                  你可以先检查并修正回答，再结束本次预览。结束后记录将保持只读。
                </p>
                <button
                  className="primary-button"
                  type="button"
                  disabled={busy}
                  onClick={endSession}
                >
                  结束诊断预览
                </button>
              </div>
            ) : null}

            {session.status !== "active" ? (
              <div className="completion-card">
                <span className="step-mark">✓</span>
                <h3>记录已锁定</h3>
                <p>
                  结束原因：{session.end_reason === "inactivity_timeout"
                    ? "连续无操作超时"
                    : "由你主动结束"}
                  。草稿预览不会生成正式计划。
                </p>
              </div>
            ) : null}

            {session.answers.length > 0 ? (
              <section className="answer-history" aria-label="已记录回答">
                <h3>回答记录</h3>
                <ol>
                  {session.answers.map((item) => (
                    <li
                      className={item.on_current_path ? "" : "off-path"}
                      key={item.id}
                    >
                      <div>
                        <span>{item.question_id}</span>
                        <p>{responseLabel(item)}</p>
                        {!item.on_current_path ? (
                          <small>路径已因修正而改变，此回答仅保留作审计。</small>
                        ) : null}
                      </div>
                      {session.status === "active" ? (
                        <button
                          className="text-button"
                          type="button"
                          disabled={busy}
                          onClick={() => beginCorrection(item)}
                        >
                          修正
                        </button>
                      ) : null}
                    </li>
                  ))}
                </ol>
              </section>
            ) : null}

            {correction && session.status === "active" ? (
              <form className="correction-form" onSubmit={saveCorrection}>
                <div>
                  <span className="eyebrow">修正回答</span>
                  <h3>{correction.question_id}</h3>
                </div>
                <label>
                  回答状态
                  <select
                    value={correctionKind}
                    disabled={busy}
                    onChange={(event) =>
                      setCorrectionKind(event.target.value as ResponseKind)
                    }
                  >
                    <option value="answered">已回答</option>
                    <option value="uncertain">不确定</option>
                    <option value="skipped">跳过</option>
                  </select>
                </label>
                {correctionKind === "answered" ? (
                  <label>
                    新回答
                    <textarea
                      value={correctionText}
                      disabled={busy}
                      onChange={(event) => setCorrectionText(event.target.value)}
                    />
                  </label>
                ) : null}
                <div className="answer-actions">
                  <button
                    className="primary-button"
                    type="submit"
                    disabled={
                      busy ||
                      (correctionKind === "answered" &&
                        correctionText.trim().length === 0)
                    }
                  >
                    保存修正
                  </button>
                  <button
                    className="text-button"
                    type="button"
                    disabled={busy}
                    onClick={() => setCorrection(null)}
                  >
                    取消
                  </button>
                </div>
              </form>
            ) : null}

            {session.status === "active" && !session.ready_to_end ? (
              <button
                className="end-link"
                type="button"
                disabled={busy}
                onClick={endSession}
              >
                提前结束本次对话
              </button>
            ) : null}
          </>
        )}
      </section>
    </div>
  );
}

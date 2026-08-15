import type { ReactNode } from "react";

export type StatusTone = "info" | "success" | "warning" | "error";

const toneLabels: Record<StatusTone, string> = {
  info: "信息",
  success: "成功",
  warning: "注意",
  error: "错误",
};

export function StatusMessage({
  tone = "info",
  title,
  children,
  id,
  priority = tone === "error" ? "assertive" : "polite",
}: Readonly<{
  tone?: StatusTone;
  title?: string;
  children: ReactNode;
  id?: string;
  priority?: "polite" | "assertive";
}>) {
  return (
    <div
      className={`status-message status-message--${tone}`}
      id={id}
      role={priority === "assertive" ? "alert" : "status"}
      aria-live={priority}
      aria-atomic="true"
    >
      <span className="status-message__mark" aria-hidden="true">
        {tone === "success" ? "✓" : tone === "error" ? "!" : "i"}
      </span>
      <div className="status-message__body">
        <span className="visually-hidden">{toneLabels[tone]}：</span>
        {title ? <strong>{title}</strong> : null}
        <div>{children}</div>
      </div>
    </div>
  );
}

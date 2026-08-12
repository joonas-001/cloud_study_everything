import type { ReactNode } from "react";

type ContextItem = {
  label: string;
  value: string;
  tone?: "neutral" | "warning" | "positive";
};

export function PageHeader({
  eyebrow,
  title,
  description,
  context = [],
  actions,
}: Readonly<{
  eyebrow: string;
  title: string;
  description: string;
  context?: readonly ContextItem[];
  actions?: ReactNode;
}>) {
  return (
    <header className="page-header">
      <div className="page-header__copy">
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        <p>{description}</p>
        {actions ? <div className="page-header__actions">{actions}</div> : null}
      </div>
      {context.length ? (
        <dl className="page-context" aria-label="页面上下文">
          {context.map((item) => (
            <div className={`page-context__item page-context__item--${item.tone ?? "neutral"}`} key={item.label}>
              <dt>{item.label}</dt>
              <dd>{item.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </header>
  );
}

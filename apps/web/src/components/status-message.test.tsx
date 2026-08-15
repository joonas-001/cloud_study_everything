import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { StatusMessage } from "./status-message";

describe("StatusMessage", () => {
  it("announces errors assertively with a textual tone label", () => {
    const markup = renderToStaticMarkup(
      <StatusMessage tone="error" title="保存失败">
        请检查输入。
      </StatusMessage>,
    );

    expect(markup).toContain('role="alert"');
    expect(markup).toContain('aria-live="assertive"');
    expect(markup).toContain("错误：");
    expect(markup).toContain("保存失败");
  });

  it("keeps ordinary warnings polite unless urgency is explicit", () => {
    const polite = renderToStaticMarkup(
      <StatusMessage tone="warning">预算接近上限。</StatusMessage>,
    );
    const urgent = renderToStaticMarkup(
      <StatusMessage tone="warning" priority="assertive">
        操作已停止。
      </StatusMessage>,
    );

    expect(polite).toContain('role="status"');
    expect(polite).toContain('aria-live="polite"');
    expect(urgent).toContain('role="alert"');
  });
});

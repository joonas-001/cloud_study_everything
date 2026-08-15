import { expect, test } from "@playwright/test";

test("keeps the milestone 7C shell and real inbox state navigable", async ({ page }, testInfo) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "今天从最明确的一步开始。" })).toBeVisible();
  await expect(page.locator(".top-nav")).toHaveCount(0);

  const skipLink = page.getByRole("link", { name: "跳到主要内容" });
  await expect(skipLink).toHaveCSS("opacity", "0");
  await expect(skipLink).toHaveCSS("clip-path", "inset(50%)");
  await expect(page.getByRole("heading", { name: "今日概览" })).toBeVisible();
  await expect(page.getByText(/当前没有到期复习|复习需要处理/)).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("m7c-today-home.png"), fullPage: true });
  await page.keyboard.press("Tab");
  await expect(skipLink).toBeFocused();
  await expect(skipLink).toHaveCSS("opacity", "1");
  await expect(skipLink).toHaveCSS("clip-path", "none");
  await page.keyboard.press("Enter");
  await expect(page.locator("#main-content")).toBeFocused();

  const viewportWidth = page.viewportSize()?.width ?? 1280;
  if (viewportWidth <= 760) {
    const mobileNavigation = page.getByRole("navigation", { name: "移动端主导航" });
    await expect(mobileNavigation).toBeVisible();
    await expect(page.getByLabel("应用导航")).toBeHidden();
    await expect(mobileNavigation.getByRole("link", { name: "今日" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await mobileNavigation.getByRole("link", { name: /证据/ }).click();
    await expect(page.getByRole("heading", { name: "看见证据，也看见证据的边界。" })).toBeVisible();
    await expect(
      page
        .getByRole("heading", { name: "还没有可汇总的学习执行" })
        .or(page.getByRole("heading", { name: "六维能力证据" })),
    ).toBeVisible();
    await mobileNavigation.getByRole("link", { name: "更多" }).click();
    await expect(page.getByRole("heading", { name: "更多一级能力" })).toBeVisible();
    await page.getByRole("link", { name: /目标与行动/ }).click();
  } else {
    const desktopNavigation = page.getByRole("navigation", { name: "主导航" });
    await expect(desktopNavigation).toBeVisible();
    await expect(page.getByRole("navigation", { name: "移动端主导航" })).toBeHidden();
    await expect(desktopNavigation.getByRole("link", { name: "今日" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await desktopNavigation.getByRole("link", { name: "证据" }).click();
    await expect(page.getByRole("heading", { name: "看见证据，也看见证据的边界。" })).toBeVisible();
    await expect(
      page
        .getByRole("heading", { name: "还没有可汇总的学习执行" })
        .or(page.getByRole("heading", { name: "六维能力证据" })),
    ).toBeVisible();
    await desktopNavigation.getByRole("link", { name: "目标与行动" }).click();
  }

  await expect(page.getByRole("heading", { name: /先明确目标/ })).toBeVisible();
  await page.goto("/inbox");
  await expect(page.getByRole("heading", { name: /需要了解、确认或处理/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "真实站内通知" })).toBeVisible();
  await expect(page.getByText(/条未读|目前没有站内通知/).first()).toBeVisible();
});

test("keeps the shell usable at an effective 200% zoom", async ({ page }) => {
  const viewport = page.viewportSize();
  if (!viewport) {
    throw new Error("The 200% zoom check requires a configured viewport.");
  }

  await page.setViewportSize({
    width: Math.floor(viewport.width / 2),
    height: viewport.height,
  });
  await page.goto("/");

  await expect(page.getByRole("navigation", { name: "移动端主导航" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "今天从最明确的一步开始。" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "今日概览" })).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      ),
    )
    .toBe(true);
});

test("applies the milestone 7E accessibility baseline", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/settings");

  const saveButton = page.getByRole("button", { name: "保存邮件设置" });
  await expect(saveButton).toBeVisible();
  await expect(saveButton).toBeEnabled();
  await saveButton.focus();
  await expect(saveButton).toBeFocused();
  await expect(saveButton).toHaveCSS("outline-style", "solid");
  await expect(saveButton).toHaveCSS("outline-width", "3px");
  const transitionDurationSeconds = await saveButton.evaluate((element) => {
    const value = getComputedStyle(element).transitionDuration;
    return value.endsWith("ms") ? Number.parseFloat(value) / 1000 : Number.parseFloat(value);
  });
  expect(transitionDurationSeconds).toBeLessThanOrEqual(0.001);

  const recipient = page.getByLabel("收件邮箱");
  await recipient.fill("not-an-email");
  expect(
    await recipient.evaluate((element) => (element as HTMLInputElement).validity.valid),
  ).toBe(false);
  const smtpPassword = page.getByLabel("SMTP 密码或应用专用密码");
  await expect(smtpPassword).toHaveAttribute("aria-describedby", "smtp-password-hint");
  await expect(page.locator("#smtp-password-hint")).toBeVisible();

  const contrast = await page.evaluate(() => {
    const styles = getComputedStyle(document.documentElement);
    const parse = (value: string) => {
      const hex = value.trim().replace("#", "");
      return [0, 2, 4].map((offset) => Number.parseInt(hex.slice(offset, offset + 2), 16));
    };
    const luminance = (value: string) => {
      const channels = parse(value).map((channel) => {
        const normalized = channel / 255;
        return normalized <= 0.03928
          ? normalized / 12.92
          : ((normalized + 0.055) / 1.055) ** 2.4;
      });
      return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
    };
    const ratio = (foreground: string, background: string) => {
      const lighter = Math.max(luminance(foreground), luminance(background));
      const darker = Math.min(luminance(foreground), luminance(background));
      return (lighter + 0.05) / (darker + 0.05);
    };
    const surface = styles.getPropertyValue("--color-surface");
    return {
      body: ratio(styles.getPropertyValue("--color-text"), surface),
      muted: ratio(styles.getPropertyValue("--color-text-muted"), surface),
      action: ratio(styles.getPropertyValue("--color-action"), surface),
    };
  });
  expect(contrast.body).toBeGreaterThanOrEqual(4.5);
  expect(contrast.muted).toBeGreaterThanOrEqual(4.5);
  expect(contrast.action).toBeGreaterThanOrEqual(4.5);

  await page.evaluate(() => {
    document.documentElement.style.fontSize = "200%";
  });
  await expect(
    page.getByRole("heading", { name: "外发之前，先把边界说清楚。" }),
  ).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      ),
    )
    .toBe(true);
  const buttonBox = await saveButton.boundingBox();
  expect(buttonBox?.height ?? 0).toBeGreaterThanOrEqual(44);

  await page.goto("/diagnostic");
  const externalAiSwitch = page.getByRole("switch", { name: "允许外部 AI" });
  await expect(externalAiSwitch).toBeEnabled();
  const switchBox = await externalAiSwitch.boundingBox();
  expect(switchBox?.width ?? 0).toBeGreaterThanOrEqual(44);
  expect(switchBox?.height ?? 0).toBeGreaterThanOrEqual(44);
});

test("completes the guarded diagnostic preview and preserves corrections", async ({
  page,
}, testInfo) => {
  test.setTimeout(60_000);
  const apiBaseUrl =
    process.env.PLAYWRIGHT_API_BASE_URL ?? "http://127.0.0.1:8000";
  await page.request.put(`${apiBaseUrl}/settings/privacy`, {
    data: { external_ai_enabled: false },
  });
  await page.request.post(`${apiBaseUrl}/__e2e__/market-reset`, {
    data: { mode: "success" },
  });
  await page.goto("/diagnostic");

  await expect(
    page.getByRole("heading", { name: "先看清起点，再安排路径。" }),
  ).toBeVisible();
  await expect(page.getByRole("switch", { name: "允许外部 AI" })).toHaveAttribute(
    "aria-checked",
    "false",
  );
  await page.getByRole("button", { name: "开始本地诊断预览" }).click();

  await expect(page.getByText("草稿预览 · 不外发")).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("diagnostic-preview.png"),
    fullPage: true,
  });
  await expect(
    page.getByRole("heading", {
      name: /你目前能否不依赖逐行示例/,
    }),
  ).toBeVisible();
  await page.getByLabel("你的回答").selectOption("independent-small-program");
  await page.getByRole("button", { name: "保存并继续" }).click();

  await expect(
    page.getByRole("heading", { name: /对函数增长、对数、逻辑命题和简单求和/ }),
  ).toBeVisible();
  await page.getByRole("button", { name: "修正" }).click();
  await page.getByLabel("回答状态").selectOption("uncertain");
  await page.getByRole("button", { name: "保存修正" }).click();

  await expect(
    page.getByRole("heading", { name: /对函数增长、对数、逻辑命题和简单求和/ }),
  ).toBeVisible();
  await page.getByRole("button", { name: "提前结束本次对话" }).click();
  await expect(page.getByRole("heading", { name: "记录已锁定" })).toBeVisible();
  await expect(page.getByText(/草稿预览不会生成正式计划/)).toBeVisible();

  await page.getByRole("link", { name: "进入学习面板" }).click();
  await expect(
    page.getByRole("heading", { name: "一次只推进一个明确任务。" }),
  ).toBeVisible();
  const generateButton = page.getByRole("button", {
    name: "生成本地规划预览",
  });
  const planningTitle = page.getByRole("heading", {
    name: "算法共同主干入口规划预览",
  });
  await expect(generateButton.or(planningTitle)).toBeVisible();
  if (await generateButton.isVisible()) {
    await generateButton.click();
  }
  await expect(planningTitle).toBeVisible();
  await expect(page.getByText("当前限制")).toBeVisible();
  await expect(page.getByRole("link", { name: /MIT OpenCourseWare/ }).first()).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("learning-plan-preview.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "否决这份预览" }).click();
  await expect(generateButton).toBeVisible();
  await generateButton.click();
  await expect(planningTitle).toBeVisible();
  await page.getByRole("button", { name: "保存这份预览" }).click();
  await expect(page.getByText("预览已保存")).toBeVisible();
  await expect(page.getByRole("heading", { name: "站内通知" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "消息已统一到收件箱" })).toHaveCount(0);

  await page.goto("/inbox");
  await expect(page.getByRole("heading", { name: "真实站内通知" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "规划预览已生成" }).first()).toBeVisible();
  const markReadButton = page.getByRole("button", { name: "标记已读" }).first();
  await expect(markReadButton).toBeVisible();
  await markReadButton.click();
  await expect(page.getByText("已读", { exact: true }).first()).toBeVisible();
  await expect(
    page.locator(".nav-item__state").filter({ hasText: /无未读|\d+ 未读/ }),
  ).toHaveAttribute("aria-label", /收件箱未读状态：(无未读|\d+ 未读)/);
  await page.goto("/learning");

  await expect(
    page.getByRole("heading", { name: "选择一份已保存规划" }),
  ).toBeVisible();
  const createRunButton = page.getByRole("button", { name: "创建学习执行锁" });
  await expect(createRunButton).toBeDisabled();
  await page
    .getByLabel(/我确认本次执行会把代码发送到本机 Docker 隔离 Runner/)
    .check();
  await expect(createRunButton).toBeEnabled();
  await createRunButton.click();
  await expect(page.getByText(/Runner：/)).toBeVisible();
  await expect(page.getByText("外部 AI：关闭")).toBeVisible();
  await page.getByRole("button", { name: "生成今日任务" }).click();
  await expect(page.getByRole("heading", { name: "编程表达补救" })).toBeVisible();
  await page.getByLabel("我已完成来源支持的复习").check();
  await page.getByRole("button", { name: "提交并继续" }).click();

  await expect(page.getByRole("heading", { name: "双语言数组遍历" })).toBeVisible();
  await page.getByLabel("我已完成阅读").check();
  await page.getByRole("button", { name: "提交并继续" }).click();

  await expect(page.getByRole("heading", { name: "边界处理检查" })).toBeVisible();
  await page.getByLabel("选择处理方式").selectOption("always-read-first");
  await page.getByRole("button", { name: "提交并继续" }).click();
  await expect(page.getByRole("button", { name: "提交追加修正" })).toBeVisible();
  await page.getByLabel("选择处理方式").selectOption("check-empty-first");
  await page.getByRole("button", { name: "提交追加修正" }).click();

  await expect(page.getByRole("heading", { name: "输入规模与增长率" })).toBeVisible();
  await expect(page.getByRole("link", { name: "打开六维证据中心" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "六维证据，不是掌握百分比" })).toHaveCount(0);
  await page.getByRole("link", { name: "打开六维证据中心" }).click();
  await expect(page.getByRole("heading", { name: "六维能力证据" })).toBeVisible();
  await expect(
    page.getByLabel("证据适用范围").getByText("最新学习执行", { exact: true }),
  ).toBeVisible();
  const latestRunResponse = await page.request.get(
    `${apiBaseUrl}/learning-run-latest?skill_id=algorithm&skill_version=0.2.2`,
  );
  expect(latestRunResponse.ok()).toBe(true);
  const latestRun = (await latestRunResponse.json()) as { id: string };
  const evidenceResponse = await page.request.get(
    `${apiBaseUrl}/learning-runs/${latestRun.id}/evidence`,
  );
  expect(evidenceResponse.ok()).toBe(true);
  const evidenceSnapshot = (await evidenceResponse.json()) as {
    dimensions: Array<{
      dimension: string;
      evidence_count: number;
      evidence_level: string;
    }>;
  };
  const dimensionTitles: Record<string, string> = {
    understanding: "知识理解",
    operation: "操作能力",
    transfer: "迁移能力",
    artifact: "作品证据",
    retention: "保持程度",
    correction: "纠错能力",
  };
  const levelTitles: Record<string, string> = {
    none: "尚无证据",
    limited: "有限证据",
    supported: "确定性支持",
    verified: "Runner 范围验证",
    retained: "延迟保持证据",
  };
  for (const dimension of evidenceSnapshot.dimensions) {
    const card = page
      .locator(".evidence-dimension")
      .filter({ hasText: dimensionTitles[dimension.dimension] });
    await expect(card).toContainText(levelTitles[dimension.evidence_level]);
    await expect(card).toContainText(`${dimension.evidence_count} 条`);
  }
  await expect(page.getByRole("heading", { name: "当前不能证明什么" })).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("m7d-evidence-center.png"),
    fullPage: true,
  });
  await page.goto("/learning");
  await page.getByRole("button", { name: "明确结束本次学习执行" }).click();
  await expect(page.getByText(/本次执行已明确结束且不可恢复/)).toBeVisible();

  await page.goto("/readiness");
  await expect(
    page.getByRole("heading", { name: "先选择目标，再决定比较是否适用。" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "保存目标" })).toBeEnabled();
  await page.getByLabel("当前目标").selectOption("exam");
  await page.getByRole("button", { name: "保存目标" }).click();
  await expect(page.getByText("已保存：准备考试")).toBeVisible();
  await expect(
    page.getByText("这是非变现目标；系统不会强制生成就业、接单或产品化建议。"),
  ).toBeVisible();
  await page.getByRole("button", { name: "生成准备度评估" }).click();
  await expect(page.getByRole("heading", { name: "本次不适用变现比较" })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "生成三路径合成比较" }),
  ).toHaveCount(0);
  await expect(page.getByText(/5B 的真实市场研究已独立接入/)).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("readiness-exam-goal.png"),
    fullPage: true,
  });
  await page.getByLabel("当前目标").selectOption("employment");
  await page.getByRole("button", { name: "保存目标" }).click();
  await expect(page.getByText("已保存：就业")).toBeVisible();
  await page.getByRole("button", { name: "生成准备度评估" }).click();

  await page.goto("/experiments");
  await expect(
    page.getByRole("heading", {
      name: "把求职假设变成可停止、可复盘的本地实验。",
    }),
  ).toBeVisible();
  await expect(page.getByText("就业准备", { exact: true })).toBeVisible();
  await expect(
    page.getByText(/没有可关联记录；真实动作会保持阻断/),
  ).toBeVisible();
  await page.getByRole("button", { name: "保存草稿并评估门禁" }).click();
  await expect(page.getByText("仅可保存草稿")).toBeVisible();
  await expect(page.getByText(/操作能力尚未达到对应范围的 verified/)).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "记录已在产品外完成的求职动作" }),
  ).toHaveCount(0);
  await expect(page.getByText("不自动执行外部动作")).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("employment-experiment-draft.png"),
    fullPage: true,
  });

  await page.goto("/diagnostic");
  await page.getByRole("switch", { name: "允许外部 AI" }).click();
  await expect(page.getByRole("switch", { name: "允许外部 AI" })).toHaveAttribute(
    "aria-checked",
    "true",
  );
  await page.goto("/market-research");
  await expect(
    page.getByRole("heading", {
      name: "先核验来源与费用，再让 AI 做有限综合。",
    }),
  ).toBeVisible();
  await expect(page.getByText("¥0.0000 / ¥5.0000")).toBeVisible();
  await expect(page.getByText("中华人民共和国国家统计局")).toBeVisible();
  await expect(page.getByText("中华人民共和国工业和信息化部")).toBeVisible();
  await expect(
    page.getByText(/成功来源 7 天后才可再次访问；访问失败后冷却 24/),
  ).toBeVisible();
  await expect(page.getByText(/首版不提供人工绕过/)).toBeVisible();
  await expect(
    page.getByText(/algorithm@0\.2\.2 · algorithm-entry-mastery-scope/),
  ).toBeVisible();
  await expect(
    page.getByText(/employment 证据能力：当前来源体系不支持判断/),
  ).toBeVisible();
  await expect(page.getByText("查看历史研究与审计事件")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "检查官方市场来源" }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "使用 deepseek-v4-flash 综合" }),
  ).toHaveCount(0);
  await page.screenshot({
    path: testInfo.outputPath("market-research-version-boundary.png"),
    fullPage: true,
  });
});

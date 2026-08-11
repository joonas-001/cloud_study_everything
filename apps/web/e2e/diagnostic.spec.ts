import { expect, test } from "@playwright/test";

test("keeps the milestone 7B shell navigable on desktop and mobile", async ({ page }, testInfo) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "今天从最明确的一步开始。" })).toBeVisible();
  await expect(page.locator(".top-nav")).toHaveCount(0);

  const skipLink = page.getByRole("link", { name: "跳到主要内容" });
  await expect(skipLink).toHaveCSS("opacity", "0");
  await expect(skipLink).toHaveCSS("clip-path", "inset(50%)");
  await page.screenshot({ path: testInfo.outputPath("m7b-shell-home.png"), fullPage: true });
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
    await expect(page.getByRole("heading", { name: /证据说明能力范围/ })).toBeVisible();
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
    await expect(page.getByRole("heading", { name: /证据说明能力范围/ })).toBeVisible();
    await desktopNavigation.getByRole("link", { name: "目标与行动" }).click();
  }

  await expect(page.getByRole("heading", { name: /先明确目标/ })).toBeVisible();
  await page.goto("/inbox");
  await expect(page.getByRole("heading", { name: /需要了解、确认或处理/ })).toBeVisible();
  await expect(page.getByText("尚未汇总", { exact: true }).first()).toBeVisible();
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
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      ),
    )
    .toBe(true);
});

test("completes the guarded diagnostic preview and preserves corrections", async ({
  page,
}, testInfo) => {
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
    page.getByRole("heading", { name: "计划可以调整，依据必须留下。" }),
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
  await expect(page.getByText("六维证据，不是掌握百分比")).toBeVisible();
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

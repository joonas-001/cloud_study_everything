import { expect, test } from "@playwright/test";

test("completes the guarded diagnostic preview and preserves corrections", async ({
  page,
}, testInfo) => {
  const apiBaseUrl =
    process.env.PLAYWRIGHT_API_BASE_URL ?? "http://127.0.0.1:8000";
  const marketMode =
    testInfo.project.name === "mobile-chromium"
      ? "model_mismatch"
      : "success";
  await page.request.put(`${apiBaseUrl}/settings/privacy`, {
    data: { external_ai_enabled: false },
  });
  await page.request.post(`${apiBaseUrl}/__e2e__/market-reset`, {
    data: { mode: marketMode },
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
  await expect(createRunButton).toBeEnabled();
  await createRunButton.click();
  await expect(page.getByText("代码执行：关闭")).toBeVisible();
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
    page.getByText(
      "algorithm@0.2.0 · algorithm-entry-mastery-scope",
    ),
  ).toBeVisible();
  await expect(
    page.getByText(/employment 证据能力：当前来源体系不支持判断/),
  ).toBeVisible();
  await expect(page.getByText("查看历史研究与审计事件")).toBeVisible();
  await expect(page.getByRole("button", { name: "检查官方市场来源" })).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "使用 deepseek-v4-flash 综合" }),
  ).toHaveCount(0);
  await page.getByLabel("确认本次访问上述官方公开来源").check();
  await page.getByRole("button", { name: "检查官方市场来源" }).click();
  await expect(page.getByText("发送前最终材料预览")).toBeVisible();
  await expect(page.getByText(/以下 4 项材料与后端实际构造综合请求/)).toBeVisible();
  await expect(page.getByText("API 密钥或凭据引用")).toBeVisible();
  await expect(
    page.getByLabel("确认删除 cn-nbs-data 的已保存摘录"),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "使用 deepseek-v4-flash 综合" }),
  ).toBeDisabled();
  await page.getByLabel("确认发送净化后的最少官方摘录给 DeepSeek").check();
  await page.getByRole("button", { name: "使用 deepseek-v4-flash 综合" }).click();

  if (marketMode === "model_mismatch") {
    await expect(page.locator(".error-banner")).toContainText(
      "响应声明的模型与锁定模型不一致",
    );
    await expect(page.getByText("本次研究已停止")).toBeVisible();
    await page.getByText("查看本次研究审计摘要").click();
    await expect(
      page.getByText("deepseek_response_model_mismatch", { exact: true }),
    ).toBeVisible();
    await expect(page.getByText("¥0.2000").first()).toBeVisible();
    await page.screenshot({
      path: testInfo.outputPath("market-research-failed-state-refreshed.png"),
      fullPage: true,
    });
    return;
  }

  await expect(page.getByText("AI 综合结果（尚未采纳）")).toBeVisible();
  await page.getByText("查看本次研究审计摘要").click();
  await expect(page.getByText(/deepseek-v4-flash \/ deepseek-v4-flash/)).toBeVisible();
  await page.getByRole("button", { name: "接受为研究记录" }).click();
  await expect(page.getByText("本次研究已结束")).toBeVisible();
  await page.getByText("逐项检查或删除已保存的净化摘录").click();
  await page.getByLabel("确认删除 cn-nbs-data 的已保存摘录").check();
  await page.getByRole("button", { name: "删除这项摘录" }).first().click();
  await expect(
    page.getByText("该综合结果所依赖的来源已撤回，只保留审计记录，不能继续采纳。"),
  ).toBeVisible();
  await page.getByText("查看历史研究与审计事件").click();
  await expect(page.getByText("source_excerpt_redacted")).toBeVisible();
  await expect(
    page.getByLabel("确认删除 cn-nbs-data 的已保存摘录"),
  ).toHaveCount(0);
  await page.screenshot({
    path: testInfo.outputPath("market-research-offline-complete-and-redacted.png"),
    fullPage: true,
  });
});

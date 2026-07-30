import { expect, test } from "@playwright/test";

test("completes the guarded diagnostic preview and preserves corrections", async ({
  page,
}, testInfo) => {
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
  await expect(page.getByText("5B、5C、真实模型、市场来源与预算仍未授权。")).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("readiness-exam-goal.png"),
    fullPage: true,
  });
});

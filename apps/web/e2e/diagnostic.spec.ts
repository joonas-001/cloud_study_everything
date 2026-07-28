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
      name: /请描述你目前使用 Python、C 或 C\+\+/,
    }),
  ).toBeVisible();
  await page
    .getByLabel("你的回答")
    .fill("我使用 Python 写过一个读取文本并统计单词的小程序。");
  await page.getByRole("button", { name: "保存并继续" }).click();

  await expect(
    page.getByRole("heading", { name: /请用自己的话比较数组和链表/ }),
  ).toBeVisible();
  await page.getByRole("button", { name: "修正" }).click();
  await page.getByLabel("回答状态").selectOption("uncertain");
  await page.getByRole("button", { name: "保存修正" }).click();

  await expect(
    page.getByRole("heading", { name: /你对变量、条件判断、循环、函数和数组/ }),
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
});

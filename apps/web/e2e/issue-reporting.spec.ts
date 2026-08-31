import { expect, test } from "@playwright/test";

test("previews, removes, and copies an allowlist-only issue diagnostic", async ({
  context,
  page,
}) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/settings");

  const panel = page.locator("section.issue-report-panel");
  await expect(panel.getByText("系统不会自动提交、评论或上传附件")).toBeVisible();
  await panel.getByRole("button", { name: "生成本地脱敏预览" }).click();

  const preview = panel.getByLabel("脱敏诊断完整预览");
  await expect(preview).toContainText("Cloud Study sanitized diagnostic v1");
  await expect(preview).toContainText("- page_route: /settings");
  await expect(preview).toContainText("- skill_version: algorithm@0.3.0");
  await expect(preview).not.toContainText("C:\\");
  await expect(preview).not.toContainText("192.168.");

  const disabledOpen = panel.getByRole("button", { name: "由我打开 GitHub 并检查" });
  await expect(disabledOpen).toBeDisabled();
  await expect(panel.getByRole("link", { name: "由我打开 GitHub 并检查" })).toHaveCount(0);

  await panel.getByRole("checkbox", { name: "页面路由" }).uncheck();
  await expect(preview).not.toContainText("page_route");

  await panel.getByRole("button", { name: "复制脱敏诊断" }).click();
  await expect(panel.getByText("脱敏诊断已复制")).toBeVisible();
  const openLink = panel.getByRole("link", { name: "由我打开 GitHub 并检查" });
  await expect(openLink).toHaveAttribute(
    "href",
    /github\.com\/joonas-001\/cloud_study_everything\/issues\/new/,
  );
  expect(await page.evaluate(() => navigator.clipboard.readText())).not.toContain("page_route");
});

test("keeps all three report forms local until the owner explicitly opens GitHub", async ({
  page,
}) => {
  await page.goto("/settings");
  const panel = page.locator("section.issue-report-panel");
  const reportType = panel.getByLabel("报告类型");

  for (const type of ["bug", "feature", "content"]) {
    await reportType.selectOption(type);
    await panel.getByRole("button", { name: "生成本地脱敏预览" }).click();
    await expect(panel.getByLabel("脱敏诊断完整预览")).toContainText(
      `- report_type: ${type}`,
    );
    await expect(panel.getByRole("button", { name: "由我打开 GitHub 并检查" })).toBeDisabled();
    await expect(panel.getByRole("link", { name: "由我打开 GitHub 并检查" })).toHaveCount(0);
  }
});

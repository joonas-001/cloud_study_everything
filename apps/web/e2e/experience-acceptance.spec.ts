import { expect, test, type Page } from "@playwright/test";

const SURFACES = [
  { path: "/", label: "今日" },
  { path: "/diagnostic", label: "诊断" },
  { path: "/learning", label: "学习" },
  { path: "/evidence", label: "证据" },
  { path: "/goals", label: "目标与行动" },
  { path: "/inbox", label: "收件箱" },
  { path: "/settings", label: "设置" },
  { path: "/readiness", label: "准备度" },
  { path: "/experiments", label: "就业实验" },
  { path: "/market-research", label: "市场研究" },
  { path: "/more", label: "更多" },
] as const;

const VISUAL_SURFACES = new Set(["/", "/evidence", "/settings"]);
const ASYNC_VIEW_TIMEOUT_MS = 15_000;

function apiBaseUrl(): string {
  return (
    process.env.PLAYWRIGHT_BROWSER_API_BASE_URL ??
    "http://127.0.0.1:3000/api"
  );
}

async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const metrics = await page.evaluate(() => {
    const clientWidth = document.documentElement.clientWidth;
    const offenders = Array.from(document.querySelectorAll<HTMLElement>("body *"))
      .map((element) => {
        const bounds = element.getBoundingClientRect();
        return {
          tag: element.tagName.toLowerCase(),
          className: element.className,
          left: Math.round(bounds.left),
          right: Math.round(bounds.right),
          scrollWidth: element.scrollWidth,
          clientWidth: element.clientWidth,
        };
      })
      .filter(
        (item) =>
          item.right > clientWidth + 1 ||
          item.left < -1 ||
          item.scrollWidth > item.clientWidth + 1,
      )
      .slice(0, 12);
    return {
      clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
      offenders,
    };
  });
  expect(
    metrics.scrollWidth,
    `页面不应横向溢出：${JSON.stringify(metrics.offenders)}`,
  ).toBeLessThanOrEqual(metrics.clientWidth + 1);
}

test("keeps every product surface readable across accepted browsers and viewports", async ({
  page,
}, testInfo) => {
  test.setTimeout(60_000);
  const pageErrors: Array<string> = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  for (const surface of SURFACES) {
    await page.goto(surface.path);
    await page.waitForLoadState("networkidle");

    const main = page.locator("main#main-content");
    await expect(main, `${surface.label}应保留唯一主要内容区域`).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("lang", "zh-CN");
    await expect(main.locator("h1"), `${surface.label}应只有一个页面主标题`).toHaveCount(1);
    await expect(main.locator("h1")).toBeVisible();
    await expectNoHorizontalOverflow(page);

    const viewportWidth = page.viewportSize()?.width ?? 1280;
    if (viewportWidth <= 760) {
      await expect(page.getByRole("navigation", { name: "移动端主导航" })).toBeVisible();
      await expect(page.getByLabel("应用导航")).toBeHidden();
    } else {
      await expect(page.getByRole("navigation", { name: "主导航" })).toBeVisible();
      await expect(page.getByRole("navigation", { name: "移动端主导航" })).toBeHidden();
    }

    await page.evaluate(() => {
      document.documentElement.style.fontSize = "200%";
    });
    await expect(main.locator("h1")).toBeVisible();
    await expectNoHorizontalOverflow(page);

    if (VISUAL_SURFACES.has(surface.path)) {
      const suffix = surface.path === "/" ? "today" : surface.path.slice(1);
      await page.screenshot({
        path: testInfo.outputPath(`m7f-${suffix}-${testInfo.project.name}.png`),
        fullPage: true,
      });
    }
    await page.evaluate(() => {
      document.documentElement.style.fontSize = "";
    });
  }

  expect(pageErrors, "跨页面读取不应产生未处理的浏览器异常").toEqual([]);
});

test("keeps visible controls named and the keyboard entry path deterministic", async (
  { page },
  testInfo,
) => {
  test.setTimeout(60_000);
  await page.goto("/settings");

  const skipLink = page.getByRole("link", { name: "跳到主要内容" });
  if (testInfo.project.name === "webkit") {
    await skipLink.focus();
  } else {
    await page.keyboard.press("Tab");
  }
  await expect(skipLink).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main-content")).toBeFocused();

  const controls = page.locator(
    'a[href], button, input:not([type="hidden"]), select, textarea, [role="switch"]',
  );
  const count = await controls.count();
  for (let index = 0; index < count; index += 1) {
    const control = controls.nth(index);
    if (await control.isVisible()) {
      await expect(control, `可见控件 ${index + 1} 必须有可访问名称`).toHaveAccessibleName(/\S/);
    }
  }

  const recipient = page.getByLabel("收件邮箱");
  await recipient.fill("not-an-email");
  expect(await recipient.evaluate((element) => (element as HTMLInputElement).validity.valid)).toBe(
    false,
  );
  await expect(page.getByLabel("SMTP 密码或应用专用密码")).toHaveAttribute(
    "aria-describedby",
    "smtp-password-hint",
  );
});

test("exposes honest loading, empty and error states", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "状态故障注入只需在基准浏览器执行一次");
  const api = apiBaseUrl();

  let releaseRequests: () => void = () => undefined;
  const requestGate = new Promise<void>((resolve) => {
    releaseRequests = resolve;
  });
  await page.route(`${api}/**`, async (route) => {
    await requestGate;
    await route.continue();
  });
  await page.goto("/");
  await expect(page.getByRole("status").filter({ hasText: "正在聚合本地任务" })).toBeVisible();
  releaseRequests();
  await page.unrouteAll({ behavior: "wait" });
  await expect(page.getByRole("heading", { name: "今日概览" })).toBeVisible({
    timeout: ASYNC_VIEW_TIMEOUT_MS,
  });

  await page.route(`${api}/learning-run-latest?**`, (route) =>
    route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ detail: { code: "not_found", message: "没有学习执行" } }),
    }),
  );
  await page.route(`${api}/experiments`, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  await page.goto("/evidence");
  await expect(page.getByRole("heading", { name: "还没有可汇总的学习执行" })).toBeVisible();
  await page.unroute(`${api}/learning-run-latest?**`);
  await page.unroute(`${api}/experiments`);

  await page.route(`${api}/notifications`, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  await page.goto("/inbox");
  await expect(page.getByRole("heading", { name: "目前没有站内通知" })).toBeVisible();
  await page.unroute(`${api}/notifications`);

  await page.route(`${api}/**`, (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        detail: { code: "acceptance_injected", message: "7F 受控错误状态" },
      }),
    }),
  );
  for (const [path, title] of [
    ["/", "今日聚合读取失败"],
    ["/evidence", "证据中心暂时无法读取"],
    ["/settings", "设置未保存"],
  ] as const) {
    await page.goto(path);
    await expect(page.getByRole("alert").filter({ hasText: title })).toBeVisible();
  }
});

test("preserves focus and status boundaries in forced-colors mode", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "强制色彩自动化在基准浏览器执行一次");
  await page.emulateMedia({ forcedColors: "active", reducedMotion: "reduce" });
  await page.goto("/settings");

  expect(await page.evaluate(() => matchMedia("(forced-colors: active)").matches)).toBe(true);
  const saveButton = page.getByRole("button", { name: "保存邮件设置" });
  await expect(saveButton).toBeEnabled();
  await saveButton.focus();
  await expect(saveButton).toBeFocused();
  await expect(saveButton).toHaveCSS("outline-style", "solid");
  await expect(saveButton).toHaveCSS("outline-width", "3px");
  await expect(saveButton).toHaveCSS("border-top-width", "2px");

  const currentNavigation = page.getByRole("navigation", { name: "主导航" }).getByRole("link", {
    name: "设置",
  });
  await expect(currentNavigation).toHaveAttribute("aria-current", "page");
  await expect(currentNavigation).toHaveCSS("outline-style", "solid");
  await expect(currentNavigation).toHaveCSS("outline-width", "2px");
});

test("survives repeated cross-area use without losing navigation context", async ({ page }) => {
  test.setTimeout(60_000);
  const pageErrors: Array<string> = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  const journey = ["/", "/learning", "/evidence", "/inbox", "/goals", "/settings"];

  for (let round = 0; round < 3; round += 1) {
    for (const path of journey) {
      await page.goto(path);
      await page.evaluate(
        () =>
          new Promise<void>((resolve) => {
            requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
          }),
      );
      await page.waitForLoadState("networkidle");
      await expect(page.locator("main#main-content h1")).toBeVisible();
      if (path === "/") {
        await expect(page.getByRole("heading", { name: "今日概览" })).toBeVisible({
          timeout: ASYNC_VIEW_TIMEOUT_MS,
        });
      }
      await expectNoHorizontalOverflow(page);
    }
  }

  expect(pageErrors, "重复跨区使用不应产生未处理异常").toEqual([]);
});

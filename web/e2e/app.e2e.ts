import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.goto("/");
});

test("端到端：可通行平面返回唯一最短路线并高亮画布", async ({ page }) => {
  // 默认 5 行 × 6 列，起点 (0,0)，出口 (2,2)
  await page.getByTestId("cell-0-0").click();
  await page.getByRole("button", { name: /② 出口/ }).click();
  await page.getByTestId("cell-2-2").click();
  await page.getByTestId("verify-button").click();

  await expect(page.getByTestId("result-ok")).toBeVisible();
  // 曼哈顿距离 4 步 = 2.0 米
  await expect(page.getByTestId("result-steps")).toHaveText("4");
  await expect(page.getByTestId("result-distance")).toHaveText("2");

  const coordSummary = page.locator("summary");
  await coordSummary.click();
  const coords = await page.getByTestId("coord-list").allInnerTexts();
  expect(coords.join("\n")).toContain("(0, 0)");
  expect(coords.join("\n")).toContain("(2, 2)");

  // 画布上确实有路线高亮
  const pathCount = await page.locator(".cell-path").count();
  expect(pathCount).toBeGreaterThanOrEqual(5);
});

test("端到端：隔断完全包围起点时明确显示不可达与真实探索数，无路线绘制", async ({
  page,
}) => {
  // 3x3 平面，起点 (1,1)，出口 (0,0)，起点四邻域全部阻挡
  await page.getByLabel("行数").fill("3");
  await page.getByLabel("列数").fill("3");
  await page.getByRole("button", { name: "应用尺寸" }).click();

  await page.getByRole("button", { name: /① 起点/ }).click();
  await page.getByTestId("cell-1-1").click();
  await page.getByRole("button", { name: /② 出口/ }).click();
  await page.getByTestId("cell-0-0").click();

  await page.getByRole("button", { name: /③ 阻挡/ }).click();
  for (const id of ["cell-0-1", "cell-1-0", "cell-1-2", "cell-2-1"]) {
    await page.getByTestId(id).click();
  }

  await page.getByTestId("verify-button").click();

  await expect(page.getByTestId("result-unreachable")).toBeVisible();
  await expect(page.getByText("不可达").first()).toBeVisible();
  await expect(page.getByTestId("explored-count")).toHaveText("1");
  expect(await page.locator(".cell-path").count()).toBe(0);
});

test("端到端：服务端拒绝起终点重合，错误反馈字段级、可操作", async ({ page }) => {
  await page.getByTestId("cell-0-0").click();
  await page.getByRole("button", { name: /② 出口/ }).click();
  await page.getByTestId("cell-0-0").click();
  await page.getByTestId("verify-button").click();

  const errorPanel = page.getByTestId("error-panel");
  await expect(errorPanel).toBeVisible();
  await expect(errorPanel).toContainText("[exit]");
  await expect(errorPanel).toContainText("不能是同一个格");
  expect(await page.locator(".cell-path").count()).toBe(0);
});

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

test("场景①：无费力格的固定样例结果不变（步数/米数/右右下下路线）", async ({ page }) => {
  // 3 行 × 3 列，起点 (0,0)，出口 (2,2)，无阻挡、无费力格
  await page.getByLabel("行数").fill("3");
  await page.getByLabel("列数").fill("3");
  await page.getByRole("button", { name: "应用尺寸" }).click();
  await page.getByRole("button", { name: /① 起点/ }).click();
  await page.getByTestId("cell-0-0").click();
  await page.getByRole("button", { name: /② 出口/ }).click();
  await page.getByTestId("cell-2-2").click();
  await page.getByTestId("verify-button").click();

  await expect(page.getByTestId("result-ok")).toBeVisible();
  await expect(page.getByTestId("result-steps")).toHaveText("4");
  await expect(page.getByTestId("result-distance")).toHaveText("2");
  // 无费力格时通行代价 = 步数
  await expect(page.getByTestId("result-cost")).toHaveText("4");
  // 等步数路线按上右下左唯一确定为 右右下下
  for (const id of ["cell-0-0", "cell-0-1", "cell-0-2", "cell-1-2", "cell-2-2"]) {
    await expect(page.locator(`[data-testid="${id}"].cell-path`)).toHaveCount(1);
  }
});

test("场景②：直线含费力格时，选择步数更长但通行代价更低的绕行", async ({ page }) => {
  // 2 行 × 4 列：起点 (0,0)，出口 (0,3)，顶排 (0,1)/(0,2) 为费力格
  await page.getByLabel("行数").fill("2");
  await page.getByLabel("列数").fill("4");
  await page.getByRole("button", { name: "应用尺寸" }).click();
  await page.getByRole("button", { name: /① 起点/ }).click();
  await page.getByTestId("cell-0-0").click();
  await page.getByRole("button", { name: /② 出口/ }).click();
  await page.getByTestId("cell-0-3").click();
  await page.getByRole("button", { name: /④ 费力/ }).click();
  await page.getByTestId("cell-0-1").click();
  await page.getByTestId("cell-0-2").click();
  await page.getByTestId("verify-button").click();

  await expect(page.getByTestId("result-ok")).toBeVisible();
  // 顶排直走 3 步但代价 7；绕底排 5 步代价 5 → 选绕行
  await expect(page.getByTestId("result-steps")).toHaveText("5");
  await expect(page.getByTestId("result-cost")).toHaveText("5");
  // 绕行路线：下、右、右、右、上
  const detour = ["cell-0-0", "cell-1-0", "cell-1-1", "cell-1-2", "cell-1-3", "cell-0-3"];
  for (const id of detour) {
    await expect(page.locator(`[data-testid="${id}"].cell-path`)).toHaveCount(1);
  }
  // 费力格仍以费力样式区分，且未被当作路线
  await expect(page.locator('[data-testid="cell-0-1"].cell-difficult')).toHaveCount(1);
  await expect(page.locator('[data-testid="cell-0-1"].cell-path')).toHaveCount(0);
});

test("场景③：等代价路线稳定命中约定路径（右右下下，不选下下右右）", async ({ page }) => {
  // 3x3，中心 (1,1) 费力：两条外圈路线都是 4 步、代价 4，约定走上边那条
  await page.getByLabel("行数").fill("3");
  await page.getByLabel("列数").fill("3");
  await page.getByRole("button", { name: "应用尺寸" }).click();
  await page.getByRole("button", { name: /① 起点/ }).click();
  await page.getByTestId("cell-0-0").click();
  await page.getByRole("button", { name: /② 出口/ }).click();
  await page.getByTestId("cell-2-2").click();
  await page.getByRole("button", { name: /④ 费力/ }).click();
  await page.getByTestId("cell-1-1").click();
  await page.getByTestId("verify-button").click();

  await expect(page.getByTestId("result-ok")).toBeVisible();
  await expect(page.getByTestId("result-cost")).toHaveText("4");
  for (const id of ["cell-0-0", "cell-0-1", "cell-0-2", "cell-1-2", "cell-2-2"]) {
    await expect(page.locator(`[data-testid="${id}"].cell-path`)).toHaveCount(1);
  }
  // 下下右右 那条不应被画成路线
  await expect(page.locator('[data-testid="cell-1-0"].cell-path')).toHaveCount(0);
});

test("场景⑤：核验贯通到通行实测——逐格计时、进度持续更新、出口锁定总耗时且原路线保留", async ({
  page,
}) => {
  // 1 行向 3 格：起点 (0,0)、出口 (0,2)，路线 (0,0)→(0,1)→(0,2)，共 2 段
  await page.getByLabel("行数").fill("2");
  await page.getByLabel("列数").fill("3");
  await page.getByRole("button", { name: "应用尺寸" }).click();
  await page.getByRole("button", { name: /① 起点/ }).click();
  await page.getByTestId("cell-0-0").click();
  await page.getByRole("button", { name: /② 出口/ }).click();
  await page.getByTestId("cell-0-2").click();
  await page.getByTestId("verify-button").click();

  await expect(page.getByTestId("result-ok")).toBeVisible();
  await expect(page.getByTestId("result-steps")).toHaveText("2");
  // 核验通过后才出现通行实测入口
  await expect(page.getByTestId("walk-start-button")).toBeVisible();

  // 发起实测：检查点停在起点，下一格是 (0,1)，累计 0、进度 0/2
  await page.getByTestId("walk-start-button").click();
  await expect(page.getByTestId("walk-running")).toBeVisible();
  await expect(page.getByTestId("walk-next")).toHaveText("(0, 1)");
  await expect(page.getByTestId("walk-elapsed")).toHaveText("0");
  await expect(page.getByTestId("walk-percent")).toContainText("0/2");

  // 非法秒数（0）：反馈留在实测面板，且不推进
  await page.getByTestId("walk-seconds-input").fill("0");
  await page.getByTestId("walk-advance-button").click();
  await expect(page.getByTestId("walk-errors")).toContainText("[seconds]");
  await expect(page.getByTestId("walk-elapsed")).toHaveText("0");
  // 原路线与核验结果不受影响
  await expect(page.locator('[data-testid="cell-0-1"].cell-path')).toHaveCount(1);
  await expect(page.getByTestId("result-ok")).toBeVisible();

  // 第 1 段：10 秒 → 到达 (0,1)
  await page.getByTestId("walk-seconds-input").fill("10");
  await page.getByTestId("walk-advance-button").click();
  await expect(page.getByTestId("walk-next")).toHaveText("(0, 2)");
  await expect(page.getByTestId("walk-elapsed")).toHaveText("10");
  await expect(page.getByTestId("walk-percent")).toContainText("1/2");

  // 第 2 段：20 秒 → 到达出口，锁定总耗时 30 秒
  await page.getByTestId("walk-seconds-input").fill("20");
  await page.getByTestId("walk-advance-button").click();
  await expect(page.getByTestId("walk-locked")).toBeVisible();
  await expect(page.getByTestId("walk-total")).toHaveText("30");
  await expect(page.getByTestId("walk-percent")).toContainText("2/2");
  // 完成后不再展示推进控件
  await expect(page.getByTestId("walk-advance-button")).toHaveCount(0);
  await expect(page.getByTestId("walk-seconds-input")).toHaveCount(0);
  // 逐段落库回显与累计一致
  await page.getByText("逐段秒数").click();
  await expect(page.getByTestId("walk-sum")).toContainText("10 + 20 = 30");
  // 整个实测过程中画布上的原路线始终保留、未被清除（一次轮询，避免逐格断言叠加超时）
  await expect
    .poll(
      () =>
        page.evaluate(() =>
          ["cell-0-0", "cell-0-1", "cell-0-2"].every(
            (id) => document.querySelector(`[data-testid="${id}"].cell-path`) !== null
          )
        ),
      { timeout: 5000 }
    )
    .toBe(true);
});

test("场景⑥：两名核验员同时确认同一实测——两次请求都成功、检查点前进两格且无服务器错误", async ({
  page,
}) => {
  // 3 格 2 段，两个并发确认都应落库并到达出口
  await page.getByLabel("行数").fill("2");
  await page.getByLabel("列数").fill("3");
  await page.getByRole("button", { name: "应用尺寸" }).click();
  await page.getByRole("button", { name: /① 起点/ }).click();
  await page.getByTestId("cell-0-0").click();
  await page.getByRole("button", { name: /② 出口/ }).click();
  await page.getByTestId("cell-0-2").click();
  await page.getByTestId("verify-button").click();
  await expect(page.getByTestId("result-ok")).toBeVisible();

  await page.getByTestId("walk-start-button").click();
  await expect(page.getByTestId("walk-running")).toBeVisible();
  const trialId = (await page.getByTestId("walk-id").textContent())?.replace(
    "实测编号：",
    ""
  ).trim() as string;
  expect(trialId.length).toBeGreaterThan(8);

  // 在页面内对同一次实测同时发起两个推进请求（模拟两名现场人员同时确认）
  const outcomes = await page.evaluate(async (id) => {
    const settle = await Promise.all(
      [10, 20].map((seconds) =>
        fetch(`/api/walk-trials/${id}/advance`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ seconds }),
        }).then(async (r) => ({ status: r.status, body: await r.json() }))
      )
    );
    return settle;
  }, trialId);

  // 两个请求都必须成功，绝不能出现 5xx
  for (const o of outcomes) {
    expect(o.status).toBe(200);
  }
  const checkpoints = outcomes.map((o) => o.body.checkpoint).sort();
  expect(checkpoints).toEqual([1, 2]);
  const final = outcomes.find((o) => o.body.completed)?.body;
  expect(final).toBeTruthy();
  expect(final.totalSeconds).toBe(30);
  expect(final.elapsedSeconds).toBe(30);
  expect(final.segments.map((s: { seconds: number }) => s.seconds).sort()).toEqual([10, 20]);
  // 两段 step 唯一连续，没有唯一键冲突导致的丢失
  expect(final.segments.map((s: { step: number }) => s.step).sort()).toEqual([1, 2]);
});

test("场景④：非法重叠返回字段错误时清空旧轨迹并高亮对应费力格", async ({ page }) => {
  await page.getByLabel("行数").fill("3");
  await page.getByLabel("列数").fill("3");
  await page.getByRole("button", { name: "应用尺寸" }).click();

  // 先得到一次成功路线
  await page.getByRole("button", { name: /① 起点/ }).click();
  await page.getByTestId("cell-0-0").click();
  await page.getByRole("button", { name: /② 出口/ }).click();
  await page.getByTestId("cell-2-2").click();
  await page.getByTestId("verify-button").click();
  await expect(page.getByTestId("result-ok")).toBeVisible();

  // 标记一个费力格；随后让服务端返回定位到 difficultCells.0 的 422
  // （模拟该费力格与阻挡格非法重叠，错误定位到提交列表索引 0 = (2,2)）
  await page.getByRole("button", { name: /④ 费力/ }).click();
  await page.getByTestId("cell-2-1").click();
  expect(await page.locator(".cell-path").count()).toBe(0); // 编辑即清旧轨迹

  await page.route("**/api/shortest-path", async (route) => {
    await route.fulfill({
      status: 422,
      contentType: "application/json",
      body: JSON.stringify({
        detail: [
          { field: "difficultCells.0", message: "费力通行格 (2,1) 不能与阻挡格重合" },
        ],
      }),
    });
  });
  await page.getByTestId("verify-button").click();

  const errorPanel = page.getByTestId("error-panel");
  await expect(errorPanel).toBeVisible();
  await expect(errorPanel).toContainText("[difficultCells.0]");
  // 不带路线：画布依旧无任何路线
  expect(await page.locator(".cell-path").count()).toBe(0);
  // 高亮索引 0 对应的费力格 (2,1)
  await expect(page.locator('[data-testid="cell-2-1"].cell-invalid')).toHaveCount(1);
});

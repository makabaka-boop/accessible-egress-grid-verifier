import { describe, expect, it } from "vitest";
import {
  applyTool,
  blockedSet,
  emptyPlan,
  resizePlan,
  sameCell,
  validateForSubmit,
} from "./grid";

describe("sameCell", () => {
  it("比较两个坐标", () => {
    expect(sameCell({ row: 1, col: 2 }, { row: 1, col: 2 })).toBe(true);
    expect(sameCell({ row: 1, col: 2 }, { row: 2, col: 1 })).toBe(false);
    expect(sameCell(null, { row: 0, col: 0 })).toBe(false);
  });
});

describe("applyTool", () => {
  it("放置并移动起点", () => {
    let plan = emptyPlan(3, 3);
    plan = applyTool(plan, "start", 0, 0);
    expect(plan.start).toEqual({ row: 0, col: 0 });
    plan = applyTool(plan, "start", 2, 2);
    expect(plan.start).toEqual({ row: 2, col: 2 });
    expect(plan.blocked).toHaveLength(0);
  });

  it("放置阻挡、且阻挡不能压在起点上", () => {
    let plan = applyTool(emptyPlan(3, 3), "start", 1, 1);
    plan = applyTool(plan, "block", 0, 0);
    expect(plan.blocked).toContainEqual({ row: 0, col: 0 });
    const before = plan.blocked.length;
    plan = applyTool(plan, "block", 1, 1);
    expect(plan.blocked).toHaveLength(before);
  });

  it("在阻挡格上放置起点会清除该格阻挡", () => {
    let plan = applyTool(emptyPlan(3, 3), "block", 1, 1);
    plan = applyTool(plan, "start", 1, 1);
    expect(plan.start).toEqual({ row: 1, col: 1 });
    expect(blockedSet(plan.blocked).has("1,1")).toBe(false);
  });

  it("费力格：可标记、幂等，且不压在起点/出口/阻挡上", () => {
    let plan = applyTool(emptyPlan(3, 3), "start", 0, 0);
    plan = applyTool(plan, "exit", 0, 1);
    plan = applyTool(plan, "block", 0, 2);

    plan = applyTool(plan, "difficult", 2, 2);
    expect(plan.difficultCells).toContainEqual({ row: 2, col: 2 });
    // 重复点击幂等：不重复添加
    const before = plan.difficultCells.length;
    plan = applyTool(plan, "difficult", 2, 2);
    expect(plan.difficultCells).toHaveLength(before);

    // 不能压在起点/出口/阻挡上
    plan = applyTool(plan, "difficult", 0, 0);
    plan = applyTool(plan, "difficult", 0, 1);
    plan = applyTool(plan, "difficult", 0, 2);
    expect(plan.difficultCells).toEqual([{ row: 2, col: 2 }]);
  });

  it("在费力格上放置阻挡/起点/出口会清掉费力标记", () => {
    let plan = applyTool(emptyPlan(3, 3), "difficult", 1, 1);
    expect(plan.difficultCells).toContainEqual({ row: 1, col: 1 });
    plan = applyTool(plan, "start", 1, 1);
    expect(plan.start).toEqual({ row: 1, col: 1 });
    expect(plan.difficultCells).toEqual([]);

    let plan2 = applyTool(emptyPlan(3, 3), "difficult", 2, 2);
    plan2 = applyTool(plan2, "block", 2, 2);
    expect(plan2.blocked).toContainEqual({ row: 2, col: 2 });
    expect(plan2.difficultCells).toEqual([]);
  });

  it("橡皮可擦除费力格", () => {
    let plan = applyTool(emptyPlan(3, 3), "difficult", 1, 1);
    plan = applyTool(plan, "erase", 1, 1);
    expect(plan.difficultCells).toEqual([]);
  });

  it("橡皮清除任意标记", () => {
    let plan = applyTool(emptyPlan(3, 3), "start", 0, 0);
    plan = applyTool(plan, "exit", 0, 1);
    plan = applyTool(plan, "block", 0, 2);
    plan = applyTool(plan, "erase", 0, 1);
    expect(plan.exit).toBeNull();
    plan = applyTool(plan, "erase", 0, 2);
    expect(plan.blocked).toEqual([]);
    plan = applyTool(plan, "erase", 0, 0);
    expect(plan.start).toBeNull();
  });
});

describe("resizePlan", () => {
  it("缩小尺寸时丢弃越界标记，保留内部标记", () => {
    let plan = emptyPlan(5, 5);
    plan = applyTool(plan, "start", 0, 0);
    plan = applyTool(plan, "exit", 4, 4);
    plan = applyTool(plan, "block", 2, 2);
    plan = applyTool(plan, "block", 4, 0);
    plan = applyTool(plan, "difficult", 1, 1);
    plan = applyTool(plan, "difficult", 3, 3);

    const shrunk = resizePlan(plan, 3, 3);
    expect(shrunk.rows).toBe(3);
    expect(shrunk.start).toEqual({ row: 0, col: 0 });
    expect(shrunk.exit).toBeNull();
    expect(shrunk.blocked).toEqual([{ row: 2, col: 2 }]);
    expect(shrunk.difficultCells).toEqual([{ row: 1, col: 1 }]);
  });
});

describe("validateForSubmit", () => {
  it("缺少起点和出口时返回字段级错误", () => {
    const result = validateForSubmit(emptyPlan(3, 3));
    expect(result.ok).toBe(false);
    if (!result.ok) {
      const fields = result.errors.map((e) => e.field);
      expect(fields).toContain("start");
      expect(fields).toContain("exit");
    }
  });

  it("完整平面返回可提交请求体", () => {
    let plan = emptyPlan(3, 3);
    plan = applyTool(plan, "start", 0, 0);
    plan = applyTool(plan, "exit", 2, 2);
    const result = validateForSubmit(plan);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.request).toEqual({
        rows: 3,
        cols: 3,
        start: { row: 0, col: 0 },
        exit: { row: 2, col: 2 },
        blocked: [],
        difficultCells: [],
      });
    }
  });
});

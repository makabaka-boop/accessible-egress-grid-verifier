import type { Cell, GridPlan, GridPlanRequest, Tool } from "../types";

export const MIN_DIM = 2;
export const MAX_DIM = 40;
export const CELL_SIZE_METERS = 0.5;

export function cellKey(r: number, c: number): string {
  return `${r},${c}`;
}

export function sameCell(a: Cell | null, b: Cell | null): boolean {
  return !!a && !!b && a.row === b.row && a.col === b.col;
}

export function emptyPlan(rows = 5, cols = 6): GridPlan {
  return { rows, cols, start: null, exit: null, blocked: [] };
}

/**把阻挡格列表转成集合，便于 O(1) 判定。 */
export function blockedSet(blocked: Cell[]): Set<string> {
  return new Set(blocked.map((c) => cellKey(c.row, c.col)));
}

/**
 * 应用一次工具点击。
 * - start / exit：放置（含从原位置移动）；
 * - block：仅当格上没有起点、出口时添加阻挡；
 * - erase：清除该格上的任何标记。
 */
export function applyTool(plan: GridPlan, tool: Tool, r: number, c: number): GridPlan {
  const next: GridPlan = {
    ...plan,
    blocked: plan.blocked.filter((b) => !(b.row === r && b.col === c)),
  };

  if (tool === "erase") {
    return {
      ...next,
      start: sameCell(plan.start, { row: r, col: c }) ? null : next.start,
      exit: sameCell(plan.exit, { row: r, col: c }) ? null : next.exit,
    };
  }

  if (tool === "start") {
    return { ...next, start: { row: r, col: c } };
  }
  if (tool === "exit") {
    return { ...next, exit: { row: r, col: c } };
  }
  // block：不能压在起点/出口上
  if (sameCell(plan.start, { row: r, col: c }) || sameCell(plan.exit, { row: r, col: c })) {
    return plan;
  }
  return { ...next, blocked: [...next.blocked, { row: r, col: c }] };
}

/**
 * 调整网格尺寸：保留仍在新范围内的阻挡格与起终点（越界则丢弃）。
 */
export function resizePlan(plan: GridPlan, rows: number, cols: number): GridPlan {
  const inside = (cell: Cell | null): cell is Cell =>
    !!cell && cell.row < rows && cell.col < cols;
  return {
    rows,
    cols,
    start: inside(plan.start) ? plan.start : null,
    exit: inside(plan.exit) ? plan.exit : null,
    blocked: plan.blocked.filter((b) => b.row < rows && b.col < cols),
  };
}

/**提交前的前端字段级校验；通过则返回可发送的请求体。 */
export type SubmitValidation =
  | { ok: true; request: GridPlanRequest }
  | { ok: false; errors: { field: string; message: string }[] };

export function validateForSubmit(plan: GridPlan): SubmitValidation {
  const errors: { field: string; message: string }[] = [];
  if (plan.rows < MIN_DIM || plan.rows > MAX_DIM) {
    errors.push({ field: "rows", message: `行数必须在 ${MIN_DIM} 至 ${MAX_DIM} 之间` });
  }
  if (plan.cols < MIN_DIM || plan.cols > MAX_DIM) {
    errors.push({ field: "cols", message: `列数必须在 ${MIN_DIM} 至 ${MAX_DIM} 之间` });
  }
  if (!plan.start) {
    errors.push({ field: "start", message: "请在网格上放置起点" });
  }
  if (!plan.exit) {
    errors.push({ field: "exit", message: "请在网格上放置出口" });
  }
  if (errors.length > 0 || !plan.start || !plan.exit) {
    return { ok: false, errors };
  }
  return {
    ok: true,
    request: {
      rows: plan.rows,
      cols: plan.cols,
      start: plan.start,
      exit: plan.exit,
      blocked: plan.blocked,
    },
  };
}

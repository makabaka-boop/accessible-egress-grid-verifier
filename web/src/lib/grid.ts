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
  return { rows, cols, start: null, exit: null, blocked: [], difficultCells: [] };
}

/**把阻挡格列表转成集合，便于 O(1) 判定。 */
export function blockedSet(blocked: Cell[]): Set<string> {
  return new Set(blocked.map((c) => cellKey(c.row, c.col)));
}

/**把费力通行格列表转成集合，便于 O(1) 判定。 */
export function difficultSet(difficultCells: Cell[]): Set<string> {
  return new Set(difficultCells.map((c) => cellKey(c.row, c.col)));
}

function withoutCell(cells: Cell[], r: number, c: number): Cell[] {
  return cells.filter((x) => !(x.row === r && x.col === c));
}

/**
 * 应用一次工具点击。
 * - start / exit：放置（含从原位置移动），并清掉目标格上的阻挡/费力标记；
 * - block：仅当格上没有起点、出口时添加阻挡（压在费力格上会清掉费力标记）；
 * - difficult：仅当格上没有起点、出口、阻挡时标记费力通行格（可反复切换幂等）；
 * - erase：清除该格上的任何标记（起点/出口/阻挡/费力）。
 */
export function applyTool(plan: GridPlan, tool: Tool, r: number, c: number): GridPlan {
  const target = { row: r, col: c };
  const onStart = sameCell(plan.start, target);
  const onExit = sameCell(plan.exit, target);
  const onBlocked = plan.blocked.some((b) => b.row === r && b.col === c);
  const onDifficult = plan.difficultCells.some((d) => d.row === r && d.col === c);

  if (tool === "erase") {
    return {
      ...plan,
      start: onStart ? null : plan.start,
      exit: onExit ? null : plan.exit,
      blocked: withoutCell(plan.blocked, r, c),
      difficultCells: withoutCell(plan.difficultCells, r, c),
    };
  }

  // 放置起点/出口：移动位置并清掉目标格上的阻挡与费力标记
  if (tool === "start") {
    return {
      ...plan,
      start: target,
      blocked: withoutCell(plan.blocked, r, c),
      difficultCells: withoutCell(plan.difficultCells, r, c),
    };
  }
  if (tool === "exit") {
    return {
      ...plan,
      exit: target,
      blocked: withoutCell(plan.blocked, r, c),
      difficultCells: withoutCell(plan.difficultCells, r, c),
    };
  }

  // block：不能压在起点/出口上；压在费力格上时改为阻挡（清掉费力标记）
  if (tool === "block") {
    if (onStart || onExit) return plan;
    if (onBlocked) return plan;
    return {
      ...plan,
      blocked: [...plan.blocked, target],
      difficultCells: onDifficult ? withoutCell(plan.difficultCells, r, c) : plan.difficultCells,
    };
  }

  // difficult：不能压在起点/出口/阻挡上；已标记则保持幂等
  if (onStart || onExit || onBlocked || onDifficult) return plan;
  return { ...plan, difficultCells: [...plan.difficultCells, target] };
}

/**
 * 调整网格尺寸：保留仍在新范围内的阻挡格、费力格与起终点（越界则丢弃）。
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
    difficultCells: plan.difficultCells.filter(
      (d) => d.row < rows && d.col < cols
    ),
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
      difficultCells: plan.difficultCells,
    },
  };
}

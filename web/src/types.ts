/**前后端共享的结构化数据类型（与 api/app/models.py 对应）。 */

export interface Cell {
  row: number;
  col: number;
}

export interface GridPlan {
  rows: number;
  cols: number;
  start: Cell | null;
  exit: Cell | null;
  blocked: Cell[];
}

/**提交给 API 的请求体（保证起点、出口均存在）。 */
export interface GridPlanRequest {
  rows: number;
  cols: number;
  start: Cell;
  exit: Cell;
  blocked: Cell[];
}

export interface PathResult {
  reachable: boolean;
  message: string;
  path: Cell[];
  steps: number | null;
  distanceMeters: number | null;
  exploredCount: number;
  explored: Cell[];
}

export interface FieldError {
  field: string;
  message: string;
}

export type Tool = "start" | "exit" | "block" | "erase";

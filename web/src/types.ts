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
  /**费力通行格（进入代价 3）；不标记时为空数组。 */
  difficultCells: Cell[];
}

/**提交给 API 的请求体（保证起点、出口均存在）。 */
export interface GridPlanRequest {
  rows: number;
  cols: number;
  start: Cell;
  exit: Cell;
  blocked: Cell[];
  /**省略时后端退化为原四方向 BFS；前端始终显式带上（空数组与省略等价）。 */
  difficultCells?: Cell[];
}

export interface PathResult {
  reachable: boolean;
  message: string;
  path: Cell[];
  steps: number | null;
  distanceMeters: number | null;
  /**累计通行代价：普通移动 1，进入费力格 3；不可达时为 null。 */
  travelCost: number | null;
  exploredCount: number;
  explored: Cell[];
}

export interface FieldError {
  field: string;
  message: string;
}

export type Tool = "start" | "exit" | "block" | "difficult" | "erase";

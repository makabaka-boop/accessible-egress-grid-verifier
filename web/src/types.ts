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

/**一次推进实测后落库返回的单段实测记录。 */
export interface WalkSegment {
  step: number;
  row: number;
  col: number;
  seconds: number;
}

/**
 * 通行实测的完整进度（创建/推进接口共用同一结构）。
 * 路线快照不可变；checkpoint 为已确认到达的格序号（0 = 仍在起点）。
 */
export interface WalkTrialProgress {
  id: string;
  status: "in_progress" | "completed";
  /**不可变路线快照（起点 → 出口）。 */
  path: Cell[];
  totalSteps: number;
  /**已确认的段数（也是当前所在格在 path 中的序号）。 */
  checkpoint: number;
  /**下一格坐标；完成后为 null。 */
  nextCoordinate: Cell | null;
  /**累计耗时（秒），由逐段秒数求和。 */
  elapsedSeconds: number;
  /**到达出口后锁定的总耗时（秒）；进行中为 null。 */
  totalSeconds: number | null;
  progressPercent: number;
  remainingSteps: number;
  completed: boolean;
  segments: WalkSegment[];
  createdAt: string;
}

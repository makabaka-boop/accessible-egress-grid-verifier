import type {
  Cell,
  FieldError,
  GridPlanRequest,
  PathResult,
  WalkTrialProgress,
} from "../types";

export class ApiError extends Error {
  /**字段级错误列表（422 响应）；网络错误等使用 field="__network__"。 */
  fieldErrors: FieldError[];

  constructor(fieldErrors: FieldError[]) {
    super(fieldErrors.map((e) => e.message).join("; "));
    this.name = "ApiError";
    this.fieldErrors = fieldErrors;
  }
}

/**解析一次 fetch：422 转字段级 ApiError，其它非 2xx 转可展示错误。 */
async function parseResponse(response: Response): Promise<unknown> {
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new ApiError([
      {
        field: "__network__",
        message: `服务返回了无法解析的响应（HTTP ${response.status}）`,
      },
    ]);
  }

  if (response.status === 422) {
    const detail = (data as { detail?: unknown })?.detail;
    if (Array.isArray(detail)) {
      const fieldErrors: FieldError[] = detail
        .filter(
          (e): e is { field: unknown; message: unknown } =>
            typeof e === "object" && e !== null
        )
        .map((e) => ({
          field: String(e.field ?? "body"),
          message: String(e.message ?? "请求字段不合法"),
        }));
      if (fieldErrors.length > 0) {
        throw new ApiError(fieldErrors);
      }
    }
    throw new ApiError([{ field: "body", message: "请求未通过服务端校验" }]);
  }

  if (!response.ok) {
    throw new ApiError([
      { field: "__network__", message: `核验服务异常（HTTP ${response.status}）` },
    ]);
  }

  return data;
}

async function postJson(url: string, body: unknown): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError([
      {
        field: "__network__",
        message: "无法连接核验服务（API），请确认 api 容器已启动后重试",
      },
    ]);
  }
  return parseResponse(response);
}

/**
 * 调用后端最短路径接口。
 * - 成功（含“不可达”）返回 PathResult；
 * - 422 抛出携带字段级错误的 ApiError，整次请求失败、不产生路线；
 * - 网络/服务器错误同样转成可展示的错误。
 */
export async function findShortestPath(
  plan: GridPlanRequest,
  baseUrl = ""
): Promise<PathResult> {
  return (await postJson(`${baseUrl}/api/shortest-path`, plan)) as PathResult;
}

/**
 * 从一次成功核验的路线快照发起通行实测。
 * 只提交不可变路线坐标，不提交整张平面。
 * 可选的单段目标秒数（1–3600 的整数）随创建一并提交；
 * 省略时请求体与旧契约完全一致（不携带 targetSeconds 字段）。
 */
export async function createWalkTrial(
  path: Cell[],
  targetSeconds?: number
): Promise<WalkTrialProgress> {
  const body: Record<string, unknown> = { path };
  if (targetSeconds !== undefined) {
    body.targetSeconds = targetSeconds;
  }
  return (await postJson("/api/walk-trials", body)) as WalkTrialProgress;
}

/**
 * 确认轮椅到达下一格，提交该段秒数；返回推进后的完整进度。
 * 秒数非法、编号不存在、完成后推进都会抛出携带字段级错误的 ApiError，
 * 且后端数据不发生变化。
 */
export async function advanceWalkTrial(
  trialId: string,
  seconds: number
): Promise<WalkTrialProgress> {
  return (await postJson(`/api/walk-trials/${trialId}/advance`, {
    seconds,
  })) as WalkTrialProgress;
}

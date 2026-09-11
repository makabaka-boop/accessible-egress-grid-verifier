import type { FieldError, GridPlanRequest, PathResult } from "../types";

export class ApiError extends Error {
  /**字段级错误列表（422 响应）；网络错误等使用 field="__network__"。 */
  fieldErrors: FieldError[];

  constructor(fieldErrors: FieldError[]) {
    super(fieldErrors.map((e) => e.message).join("; "));
    this.name = "ApiError";
    this.fieldErrors = fieldErrors;
  }
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
  let response: Response;
  try {
    response = await fetch(`${baseUrl}/api/shortest-path`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(plan),
    });
  } catch {
    throw new ApiError([
      {
        field: "__network__",
        message: "无法连接核验服务（API），请确认 api 容器已启动后重试",
      },
    ]);
  }

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

  return data as PathResult;
}

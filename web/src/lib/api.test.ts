import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, findShortestPath } from "./api";
import type { GridPlanRequest } from "../types";

const VALID_PLAN: GridPlanRequest = {
  rows: 3,
  cols: 3,
  start: { row: 0, col: 0 },
  exit: { row: 2, col: 2 },
  blocked: [],
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("findShortestPath", () => {
  it("成功时返回路线结果", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            reachable: true,
            message: "找到唯一最短路线",
            path: [
              { row: 0, col: 0 },
              { row: 0, col: 1 },
            ],
            steps: 1,
            distanceMeters: 0.5,
            exploredCount: 2,
            explored: [
              { row: 0, col: 0 },
              { row: 0, col: 1 },
            ],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        )
      )
    );

    const result = await findShortestPath(VALID_PLAN);
    expect(result.reachable).toBe(true);
    expect(result.steps).toBe(1);
    expect(result.distanceMeters).toBe(0.5);
  });

  it("422 时抛出含字段级错误的 ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            detail: [
              { field: "start", message: "起点位于阻挡格上，疏散路线无法开始" },
              { field: "exit", message: "出口与起点不能是同一个格" },
            ],
          }),
          { status: 422, headers: { "Content-Type": "application/json" } }
        )
      )
    ));

    await expect(findShortestPath(VALID_PLAN)).rejects.toBeInstanceOf(ApiError);
    const err = await findShortestPath(VALID_PLAN).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).fieldErrors.map((e) => e.field)).toEqual(["start", "exit"]);
  });

  it("不可达结果正常返回（非异常）", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            reachable: false,
            message: "不可达",
            path: [],
            steps: null,
            distanceMeters: null,
            exploredCount: 4,
            explored: [
              { row: 0, col: 0 },
              { row: 1, col: 0 },
              { row: 2, col: 0 },
              { row: 3, col: 0 },
            ],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        )
      )
    );

    const result = await findShortestPath(VALID_PLAN);
    expect(result.reachable).toBe(false);
    expect(result.exploredCount).toBe(4);
    expect(result.path).toEqual([]);
  });

  it("网络失败转成可展示错误", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network down")));
    try {
      await findShortestPath(VALID_PLAN);
      throw new Error("应当抛出异常");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).fieldErrors[0].field).toBe("__network__");
    }
  });

  it("按契约发送 JSON 请求体", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          reachable: true,
          path: [],
          steps: 0,
          distanceMeters: 0,
          exploredCount: 1,
          explored: [],
          message: "",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      )
    );
    vi.stubGlobal("fetch", fetchMock);

    await findShortestPath(VALID_PLAN);
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/shortest-path");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual(VALID_PLAN);
  });
});

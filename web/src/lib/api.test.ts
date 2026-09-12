import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  advanceWalkTrial,
  createWalkTrial,
  findShortestPath,
} from "./api";
import type { GridPlanRequest } from "../types";

const VALID_PLAN: GridPlanRequest = {
  rows: 3,
  cols: 3,
  start: { row: 0, col: 0 },
  exit: { row: 2, col: 2 },
  blocked: [],
  difficultCells: [],
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

describe("通行实测 API", () => {
  const trialProgress = {
    id: "t1",
    status: "in_progress",
    path: [
      { row: 0, col: 0 },
      { row: 0, col: 1 },
    ],
    totalSteps: 1,
    checkpoint: 0,
    nextCoordinate: { row: 0, col: 1 },
    elapsedSeconds: 0,
    totalSeconds: null,
    progressPercent: 0,
    remainingSteps: 1,
    completed: false,
    segments: [],
    createdAt: "2026-01-01T00:00:00Z",
  };

  it("createWalkTrial 只提交路线快照", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify(trialProgress), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      );
    vi.stubGlobal("fetch", fetchMock);

    const result = await createWalkTrial(trialProgress.path);
    expect(result.id).toBe("t1");
    expect(result.nextCoordinate).toEqual({ row: 0, col: 1 });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/walk-trials");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ path: trialProgress.path });
  });

  it("createWalkTrial 携带可选单段目标秒数", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(
          JSON.stringify({
            ...trialProgress,
            targetSeconds: 30,
            verdictSummary: {
              onTargetCount: 0,
              overtimeCount: 0,
              onTargetCoordinates: [],
              overtimeCoordinates: [],
            },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        )
      );
    vi.stubGlobal("fetch", fetchMock);

    const result = await createWalkTrial(trialProgress.path, 30);
    expect(result.targetSeconds).toBe(30);
    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init.body)).toEqual({ path: trialProgress.path, targetSeconds: 30 });
  });

  it("createWalkTrial 省略目标时请求体不含 targetSeconds（旧契约）", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify(trialProgress), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      );
    vi.stubGlobal("fetch", fetchMock);

    await createWalkTrial(trialProgress.path);
    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init.body)).toEqual({ path: trialProgress.path });
    expect("targetSeconds" in JSON.parse(init.body)).toBe(false);
  });

  it("advanceWalkTrial 提交秒数并返回推进后进度", async () => {
    const after = {
      ...trialProgress,
      status: "completed",
      checkpoint: 1,
      nextCoordinate: null,
      elapsedSeconds: 42,
      totalSeconds: 42,
      progressPercent: 100,
      remainingSteps: 0,
      completed: true,
      segments: [{ step: 1, row: 0, col: 1, seconds: 42 }],
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify(after), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      );
    vi.stubGlobal("fetch", fetchMock);

    const result = await advanceWalkTrial("t1", 42);
    expect(result.completed).toBe(true);
    expect(result.totalSeconds).toBe(42);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/walk-trials/t1/advance");
    expect(JSON.parse(init.body)).toEqual({ seconds: 42 });
  });

  it("秒数非法返回 422 时抛出字段级 ApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() =>
        Promise.resolve(
          new Response(
            JSON.stringify({
              detail: [{ field: "seconds", message: "秒数必须在 1 至 3600 之间" }],
            }),
            { status: 422, headers: { "Content-Type": "application/json" } }
          )
        )
      )
    );
    const err = await advanceWalkTrial("t1", 0).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).fieldErrors[0].field).toBe("seconds");
  });

  it("实测编号不存在返回 422 时定位到 trialId", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() =>
        Promise.resolve(
          new Response(
            JSON.stringify({
              detail: [{ field: "trialId", message: "实测编号不存在：nope" }],
            }),
            { status: 422, headers: { "Content-Type": "application/json" } }
          )
        )
      )
    );
    const err = await advanceWalkTrial("nope", 10).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).fieldErrors[0].field).toBe("trialId");
  });
});

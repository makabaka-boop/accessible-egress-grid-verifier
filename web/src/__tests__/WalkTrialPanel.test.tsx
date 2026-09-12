import { describe, expect, it, vi, afterEach, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { WalkTrialPanel } from "../components/WalkTrialPanel";

const PATH_3 = [
  { row: 0, col: 0 },
  { row: 0, col: 1 },
  { row: 0, col: 2 },
];

function progress(overrides: Record<string, unknown> = {}) {
  return {
    id: "abc123",
    status: "in_progress",
    path: PATH_3,
    totalSteps: 2,
    checkpoint: 0,
    nextCoordinate: { row: 0, col: 1 },
    elapsedSeconds: 0,
    totalSeconds: null,
    targetSeconds: null,
    verdictSummary: null,
    progressPercent: 0,
    remainingSteps: 2,
    completed: false,
    segments: [],
    createdAt: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  document.body.innerHTML = "";
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("WalkTrialPanel", () => {
  it("发起实测：提交不可变路线快照并显示下一坐标、累计与进度", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(progress()))
      .mockResolvedValueOnce(
        jsonResponse(
          progress({
            checkpoint: 1,
            nextCoordinate: { row: 0, col: 2 },
            elapsedSeconds: 10,
            progressPercent: 50,
            remainingSteps: 1,
            segments: [{ step: 1, row: 0, col: 1, seconds: 10 }],
          })
        )
      )
      .mockResolvedValueOnce(
        jsonResponse(
          progress({
            status: "completed",
            checkpoint: 2,
            nextCoordinate: null,
            elapsedSeconds: 35,
            totalSeconds: 35,
            progressPercent: 100,
            remainingSteps: 0,
            completed: true,
            segments: [
              { step: 1, row: 0, col: 1, seconds: 10 },
              { step: 2, row: 0, col: 2, seconds: 25 },
            ],
          })
        )
      );
    vi.stubGlobal("fetch", fetchMock);
    render(<WalkTrialPanel snapshot={PATH_3} />);

    // 发起前只有按钮，不显示运行区
    expect(screen.queryByTestId("walk-running")).toBeNull();
    fireEvent.click(screen.getByTestId("walk-start-button"));

    await waitFor(() => expect(screen.getByTestId("walk-running")).toBeTruthy());
    // 创建请求只携带路线快照
    const [createUrl, createInit] = fetchMock.mock.calls[0];
    expect(createUrl).toBe("/api/walk-trials");
    expect(JSON.parse(createInit.body)).toEqual({ path: PATH_3 });
    expect(screen.getByTestId("walk-next").textContent).toBe("(0, 1)");
    expect(screen.getByTestId("walk-elapsed").textContent).toBe("0");
    expect(screen.getByTestId("walk-percent").textContent).toContain("0/2");

    // 第一段：10 秒
    fireEvent.change(screen.getByTestId("walk-seconds-input"), { target: { value: "10" } });
    fireEvent.click(screen.getByTestId("walk-advance-button"));
    await waitFor(() => expect(screen.getByTestId("walk-elapsed").textContent).toBe("10"));
    expect(screen.getByTestId("walk-next").textContent).toBe("(0, 2)");
    expect(screen.getByTestId("walk-percent").textContent).toContain("1/2");
    const [advanceUrl1, advanceInit1] = fetchMock.mock.calls[1];
    expect(advanceUrl1).toBe("/api/walk-trials/abc123/advance");
    expect(JSON.parse(advanceInit1.body)).toEqual({ seconds: 10 });

    // 第二段：25 秒，到达出口锁定
    fireEvent.change(screen.getByTestId("walk-seconds-input"), { target: { value: "25" } });
    fireEvent.click(screen.getByTestId("walk-advance-button"));
    await waitFor(() => expect(screen.getByTestId("walk-locked")).toBeTruthy());
    expect(screen.getByTestId("walk-total").textContent).toBe("35");
    expect(screen.getByTestId("walk-percent").textContent).toContain("2/2");
    // 完成后不再显示推进输入与按钮
    expect(screen.queryByTestId("walk-seconds-input")).toBeNull();
    expect(screen.queryByTestId("walk-advance-button")).toBeNull();
    // 不再显示下一坐标/进行中累计
    expect(screen.queryByTestId("walk-next")).toBeNull();
  });

  it("秒数前端校验：非 1-3600 整数时在面板内提示且不发请求", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(progress()));
    vi.stubGlobal("fetch", fetchMock);
    render(<WalkTrialPanel snapshot={PATH_3} />);
    fireEvent.click(screen.getByTestId("walk-start-button"));
    await waitFor(() => expect(screen.getByTestId("walk-running")).toBeTruthy());
    const callsAfterStart = fetchMock.mock.calls.length;

    fireEvent.change(screen.getByTestId("walk-seconds-input"), { target: { value: "0" } });
    fireEvent.click(screen.getByTestId("walk-advance-button"));
    expect(screen.getByTestId("walk-errors").textContent).toContain("seconds");
    expect(screen.getByTestId("walk-errors").textContent).toContain("1 至 3600");
    expect(fetchMock.mock.calls.length).toBe(callsAfterStart);

    fireEvent.change(screen.getByTestId("walk-seconds-input"), { target: { value: "abc" } });
    fireEvent.click(screen.getByTestId("walk-advance-button"));
    expect(screen.getByTestId("walk-errors").textContent).toContain("整数");
    expect(fetchMock.mock.calls.length).toBe(callsAfterStart);
  });

  it("推进返回 422（如完成后继续推进）：字段级错误留在实测面板，进度不清空", async () => {
    const fetchMock = vi
      .fn()
      // 创建
      .mockResolvedValueOnce(jsonResponse(progress()))
      // 第一段成功
      .mockResolvedValueOnce(
        jsonResponse(
          progress({
            checkpoint: 1,
            nextCoordinate: { row: 0, col: 2 },
            elapsedSeconds: 10,
            progressPercent: 50,
            remainingSteps: 1,
            segments: [{ step: 1, row: 0, col: 1, seconds: 10 }],
          })
        )
      )
      // 第二段被服务端拒绝（模拟完成后推进）
      .mockResolvedValueOnce(
        jsonResponse(
          { detail: [{ field: "completed", message: "该实测已到达出口并锁定总耗时，不能继续推进" }] },
          422
        )
      );
    vi.stubGlobal("fetch", fetchMock);
    render(<WalkTrialPanel snapshot={PATH_3} />);
    fireEvent.click(screen.getByTestId("walk-start-button"));
    await waitFor(() => expect(screen.getByTestId("walk-running")).toBeTruthy());

    fireEvent.change(screen.getByTestId("walk-seconds-input"), { target: { value: "10" } });
    fireEvent.click(screen.getByTestId("walk-advance-button"));
    await waitFor(() => expect(screen.getByTestId("walk-elapsed").textContent).toBe("10"));

    fireEvent.change(screen.getByTestId("walk-seconds-input"), { target: { value: "5" } });
    fireEvent.click(screen.getByTestId("walk-advance-button"));
    await waitFor(() => expect(screen.getByTestId("walk-errors")).toBeTruthy());
    expect(screen.getByTestId("walk-errors").textContent).toContain("[completed]");
    expect(screen.getByTestId("walk-errors").textContent).toContain("锁定");
    // 进度仍是拒绝前的状态，未被清空
    expect(screen.getByTestId("walk-elapsed").textContent).toBe("10");
    expect(screen.getByTestId("walk-next").textContent).toBe("(0, 2)");
  });

  it("发起实测失败也只在实测面板内反馈", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(
          jsonResponse({ detail: [{ field: "path", message: "路线至少需要 2 格" }] }, 422)
        )
    );
    render(<WalkTrialPanel snapshot={PATH_3} />);
    fireEvent.click(screen.getByTestId("walk-start-button"));
    await waitFor(() => expect(screen.getByTestId("walk-errors")).toBeTruthy());
    expect(screen.getByTestId("walk-errors").textContent).toContain("[path]");
    // 未进入运行态
    expect(screen.queryByTestId("walk-running")).toBeNull();
  });

  it("设定单段目标：创建请求携带目标，推进后即时汇总超时/达标与坐标", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse(
          progress({
            targetSeconds: 15,
            verdictSummary: {
              onTargetCount: 0,
              overtimeCount: 0,
              onTargetCoordinates: [],
              overtimeCoordinates: [],
            },
          })
        )
      )
      .mockResolvedValueOnce(
        jsonResponse(
          progress({
            targetSeconds: 15,
            checkpoint: 1,
            nextCoordinate: { row: 0, col: 2 },
            elapsedSeconds: 10,
            progressPercent: 50,
            remainingSteps: 1,
            segments: [{ step: 1, row: 0, col: 1, seconds: 10, verdict: "on_target" }],
            verdictSummary: {
              onTargetCount: 1,
              overtimeCount: 0,
              onTargetCoordinates: [{ row: 0, col: 1 }],
              overtimeCoordinates: [],
            },
          })
        )
      )
      .mockResolvedValueOnce(
        jsonResponse(
          progress({
            targetSeconds: 15,
            status: "completed",
            checkpoint: 2,
            nextCoordinate: null,
            elapsedSeconds: 30,
            totalSeconds: 30,
            progressPercent: 100,
            remainingSteps: 0,
            completed: true,
            segments: [
              { step: 1, row: 0, col: 1, seconds: 10, verdict: "on_target" },
              { step: 2, row: 0, col: 2, seconds: 20, verdict: "overtime" },
            ],
            verdictSummary: {
              onTargetCount: 1,
              overtimeCount: 1,
              onTargetCoordinates: [{ row: 0, col: 1 }],
              overtimeCoordinates: [{ row: 0, col: 2 }],
            },
          })
        )
      );
    vi.stubGlobal("fetch", fetchMock);
    render(<WalkTrialPanel snapshot={PATH_3} />);

    // 填写目标 15 秒后发起
    fireEvent.change(screen.getByTestId("walk-target-input"), { target: { value: "15" } });
    fireEvent.click(screen.getByTestId("walk-start-button"));
    await waitFor(() => expect(screen.getByTestId("walk-running")).toBeTruthy());
    const [, createInit] = fetchMock.mock.calls[0];
    expect(JSON.parse(createInit.body)).toEqual({ path: PATH_3, targetSeconds: 15 });
    expect(screen.getByTestId("walk-target-display").textContent).toBe("15");
    expect(screen.getByTestId("walk-ontarget-count").textContent).toContain("0");
    expect(screen.getByTestId("walk-overtime-coords").textContent).toBe("无");

    // 第 1 段 10 秒（达标）：汇总即时更新
    fireEvent.change(screen.getByTestId("walk-seconds-input"), { target: { value: "10" } });
    fireEvent.click(screen.getByTestId("walk-advance-button"));
    await waitFor(() =>
      expect(screen.getByTestId("walk-ontarget-count").textContent).toContain("1")
    );
    expect(screen.getByTestId("walk-overtime-count").textContent).toContain("0");
    expect(screen.getByTestId("walk-ontarget-coords").textContent).toContain("(0, 1)");

    // 第 2 段 20 秒（超时）：完成后汇总含超时坐标
    fireEvent.change(screen.getByTestId("walk-seconds-input"), { target: { value: "20" } });
    fireEvent.click(screen.getByTestId("walk-advance-button"));
    await waitFor(() => expect(screen.getByTestId("walk-locked")).toBeTruthy());
    expect(screen.getByTestId("walk-overtime-count").textContent).toContain("1");
    expect(screen.getByTestId("walk-overtime-coords").textContent).toContain("(0, 2)");
    expect(screen.getByTestId("walk-ontarget-coords").textContent).toContain("(0, 1)");
  });

  it("目标值非法：面板内提示且不发起请求，已填写的值保留可修正", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<WalkTrialPanel snapshot={PATH_3} />);

    const input = screen.getByTestId("walk-target-input") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "0" } });
    fireEvent.click(screen.getByTestId("walk-start-button"));
    expect(screen.getByTestId("walk-errors").textContent).toContain("targetSeconds");
    expect(screen.getByTestId("walk-errors").textContent).toContain("1 至 3600");
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.queryByTestId("walk-running")).toBeNull();
    // 用户填写值保留，便于修正后重试
    expect(input.value).toBe("0");

    fireEvent.change(input, { target: { value: "abc" } });
    fireEvent.click(screen.getByTestId("walk-start-button"));
    expect(screen.getByTestId("walk-errors").textContent).toContain("整数");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("服务端拒绝目标值（422 targetSeconds）：反馈留在面板，路线与填写值保留", async () => {
    // 输入通过前端校验（模拟服务端更严格的判定或直接命中服务端校验）
    const fetchMock = vi.fn().mockResolvedValueOnce(
      jsonResponse(
        { detail: [{ field: "targetSeconds", message: "目标秒数必须是 1 至 3600 之间的整数" }] },
        422
      )
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<WalkTrialPanel snapshot={PATH_3} />);

    const input = screen.getByTestId("walk-target-input") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "30" } });
    fireEvent.click(screen.getByTestId("walk-start-button"));
    await waitFor(() => expect(screen.getByTestId("walk-errors")).toBeTruthy());
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("walk-errors").textContent).toContain("[targetSeconds]");
    // 未进入运行态，已填写的目标值保留，可修正后重试
    expect(screen.queryByTestId("walk-running")).toBeNull();
    expect(input.value).toBe("30");
  });

  it("留空目标：创建请求不携带 targetSeconds，不显示判定汇总", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(progress()))
      .mockResolvedValueOnce(
        jsonResponse(
          progress({
            checkpoint: 1,
            nextCoordinate: { row: 0, col: 2 },
            elapsedSeconds: 10,
            progressPercent: 50,
            remainingSteps: 1,
            segments: [{ step: 1, row: 0, col: 1, seconds: 10, verdict: null }],
          })
        )
      );
    vi.stubGlobal("fetch", fetchMock);
    render(<WalkTrialPanel snapshot={PATH_3} />);

    fireEvent.click(screen.getByTestId("walk-start-button"));
    await waitFor(() => expect(screen.getByTestId("walk-running")).toBeTruthy());
    const [, createInit] = fetchMock.mock.calls[0];
    expect(JSON.parse(createInit.body)).toEqual({ path: PATH_3 });
    expect(screen.queryByTestId("walk-verdict-summary")).toBeNull();
    expect(screen.queryByTestId("walk-target-display")).toBeNull();

    fireEvent.change(screen.getByTestId("walk-seconds-input"), { target: { value: "10" } });
    fireEvent.click(screen.getByTestId("walk-advance-button"));
    await waitFor(() => expect(screen.getByTestId("walk-elapsed").textContent).toBe("10"));
    expect(screen.queryByTestId("walk-verdict-summary")).toBeNull();
  });
});

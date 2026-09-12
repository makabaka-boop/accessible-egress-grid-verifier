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
});

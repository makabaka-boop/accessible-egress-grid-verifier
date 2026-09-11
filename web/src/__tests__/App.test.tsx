import { describe, expect, it, vi, afterEach, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import App from "../App";

function okResponse(overrides: Record<string, unknown> = {}) {
  return {
    reachable: true,
    message: "找到唯一最短路线",
    path: [
      { row: 0, col: 0 },
      { row: 0, col: 1 },
      { row: 1, col: 1 },
    ],
    steps: 2,
    distanceMeters: 1.0,
    exploredCount: 3,
    explored: [
      { row: 0, col: 0 },
      { row: 0, col: 1 },
      { row: 1, col: 1 },
    ],
    ...overrides,
  };
}

beforeEach(() => {
  document.body.innerHTML = "";
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("App 编辑器交互", () => {
  it("未放置起点出口时核验，显示字段级错误且不发起请求", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    fireEvent.click(screen.getByTestId("verify-button"));
    expect(screen.getByTestId("error-panel")).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByText(/请在网格上放置起点/)).toBeTruthy();
  });

  it("成功流程：点击格放置起终点，提交后渲染步数、距离与路线格", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify(okResponse()), { status: 200 }))
    );
    render(<App />);

    // 默认工具是“起点”
    fireEvent.click(screen.getByTestId("cell-0-0"));
    fireEvent.click(screen.getByRole("button", { name: /② 出口/ }));
    fireEvent.click(screen.getByTestId("cell-1-1"));
    fireEvent.click(screen.getByTestId("verify-button"));

    await waitFor(() => expect(screen.getByTestId("result-ok")).toBeTruthy());
    expect(screen.getByTestId("result-steps").textContent).toBe("2");
    expect(screen.getByTestId("result-distance").textContent).toBe("1");
    expect(screen.getByTestId("cell-0-1").className).toContain("cell-path");
  });

  it("不可达时显示警示、真实探索数，且画布不绘制路线", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify(
            okResponse({
              reachable: false,
              message: "不可达",
              path: [],
              steps: null,
              distanceMeters: null,
              exploredCount: 1,
              explored: [{ row: 0, col: 0 }],
            })
          ),
          { status: 200 }
        )
      )
    );
    render(<App />);

    fireEvent.click(screen.getByTestId("cell-0-0"));
    fireEvent.click(screen.getByRole("button", { name: /② 出口/ }));
    // 出口放在 (4,5)（默认 5x6 网格内）
    fireEvent.click(screen.getByTestId("cell-4-5"));
    fireEvent.click(screen.getByTestId("verify-button"));

    await waitFor(() => expect(screen.getByTestId("result-unreachable")).toBeTruthy());
    expect(screen.getByText("不可达")).toBeTruthy();
    expect(screen.getByTestId("explored-count").textContent).toBe("1");
    expect(document.querySelectorAll(".cell-path").length).toBe(0);
    expect(screen.getByTestId("cell-0-0").className).toContain("cell-explored");
  });

  it("422 后再次编辑会清掉错误与旧结果", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            detail: [{ field: "exit", message: "出口与起点不能是同一个格" }],
          }),
          { status: 422 }
        )
      )
      .mockResolvedValueOnce(new Response(JSON.stringify(okResponse()), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
    fireEvent.click(screen.getByTestId("cell-0-0"));
    fireEvent.click(screen.getByRole("button", { name: /② 出口/ }));
    fireEvent.click(screen.getByTestId("cell-0-0")); // 与起点重合
    fireEvent.click(screen.getByTestId("verify-button"));

    await waitFor(() => expect(screen.getByTestId("error-panel")).toBeTruthy());
    expect(screen.getByText(/不能是同一个格/)).toBeTruthy();

    // 修改平面：错误面板与路线结果都应消失（mutatePlan 会清空）
    fireEvent.click(screen.getByTestId("cell-2-2"));
    expect(screen.queryByTestId("error-panel")).toBeNull();
    expect(screen.queryByTestId("result-ok")).toBeNull();
  });

  it("成功之后再编辑网格，旧路线不残留在画布上", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify(okResponse()), { status: 200 }))
    );
    render(<App />);

    fireEvent.click(screen.getByTestId("cell-0-0"));
    fireEvent.click(screen.getByRole("button", { name: /② 出口/ }));
    fireEvent.click(screen.getByTestId("cell-1-1"));
    fireEvent.click(screen.getByTestId("verify-button"));

    await waitFor(() => expect(screen.getByTestId("result-ok")).toBeTruthy());
    expect(document.querySelectorAll(".cell-path").length).toBeGreaterThan(0);

    // 放置一个阻挡格，触发 mutatePlan
    fireEvent.click(screen.getByRole("button", { name: /③ 阻挡/ }));
    fireEvent.click(screen.getByTestId("cell-3-3"));
    expect(document.querySelectorAll(".cell-path").length).toBe(0);
    expect(screen.queryByTestId("result-ok")).toBeNull();
  });

  it("非法行列尺寸被前端拒绝，显示可操作提示", () => {
    render(<App />);
    const rowsInput = screen.getByLabelText("行数") as HTMLInputElement;
    fireEvent.change(rowsInput, { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "应用尺寸" }));
    expect(screen.getByText(/行数必须是 2 至 40 之间的整数/)).toBeTruthy();
  });
});

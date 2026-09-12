import { useMemo, useRef, useState } from "react";
import type { FieldError, GridPlan, PathResult, Tool } from "./types";
import {
  MAX_DIM,
  MIN_DIM,
  applyTool,
  cellKey,
  emptyPlan,
  resizePlan,
  validateForSubmit,
} from "./lib/grid";
import { ApiError, findShortestPath } from "./lib/api";
import { GridEditor } from "./components/GridEditor";
import { ErrorPanel } from "./components/ErrorPanel";
import { ResultPanel } from "./components/ResultPanel";

const TOOLS: { id: Tool; label: string; hint: string }[] = [
  { id: "start", label: "① 起点", hint: "点击格放置起点" },
  { id: "exit", label: "② 出口", hint: "点击格放置出口" },
  { id: "block", label: "③ 阻挡", hint: "点击格放置临时隔断" },
  { id: "difficult", label: "④ 费力", hint: "点击格标记费力通行格（进入代价为 3）" },
  { id: "erase", label: "橡皮", hint: "点击格清除标记" },
];

function parseDim(value: string): number {
  if (!/^\d+$/.test(value.trim())) return NaN;
  return Number(value.trim());
}

export default function App() {
  const [plan, setPlan] = useState<GridPlan>(() => emptyPlan());
  const [rowsInput, setRowsInput] = useState("5");
  const [colsInput, setColsInput] = useState("6");
  const [tool, setTool] = useState<Tool>("start");
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [result, setResult] = useState<PathResult | null>(null);
  const [loading, setLoading] = useState(false);
  // 平面版本：任何编辑都会自增，用于识别并丢弃编辑前发出的过期响应；
  // 请求序号：区分先后发起的核验，避免旧请求干扰新请求的加载态。
  const planVersionRef = useRef(0);
  const requestSeqRef = useRef(0);

  // 任何对平面的编辑都会作废上一次的结果，画布不残留旧路线。
  function mutatePlan(next: GridPlan) {
    planVersionRef.current += 1;
    setPlan(next);
    setResult(null);
    setErrors([]);
  }

  function handleCellClick(r: number, c: number) {
    mutatePlan(applyTool(plan, tool, r, c));
  }

  function applyDimensions() {
    const rows = parseDim(rowsInput);
    const cols = parseDim(colsInput);
    const nextErrors: FieldError[] = [];
    if (!Number.isInteger(rows) || rows < MIN_DIM || rows > MAX_DIM) {
      nextErrors.push({
        field: "rows",
        message: `行数必须是 ${MIN_DIM} 至 ${MAX_DIM} 之间的整数`,
      });
    }
    if (!Number.isInteger(cols) || cols < MIN_DIM || cols > MAX_DIM) {
      nextErrors.push({
        field: "cols",
        message: `列数必须是 ${MIN_DIM} 至 ${MAX_DIM} 之间的整数`,
      });
    }
    if (nextErrors.length > 0) {
      setErrors(nextErrors);
      return;
    }
    setErrors([]);
    mutatePlan(resizePlan(plan, rows, cols));
  }

  async function handleVerify() {
    setResult(null); // 先清画布，绝不残留上一次成功路线
    const validation = validateForSubmit(plan);
    if (!validation.ok) {
      setErrors(validation.errors);
      return;
    }
    setErrors([]);
    setLoading(true);
    const seq = ++requestSeqRef.current;
    const versionAtSend = planVersionRef.current;
    // 等待期间平面被编辑（或发起了更新的请求）时，本次响应即为过期数据
    const isStale = () =>
      seq !== requestSeqRef.current || planVersionRef.current !== versionAtSend;
    try {
      const apiResult = await findShortestPath(validation.request);
      if (isStale()) return; // 编辑前的请求返回：丢弃，保持结果清空
      setResult(apiResult);
    } catch (err) {
      if (isStale()) return;
      if (err instanceof ApiError) {
        setErrors(err.fieldErrors);
      } else {
        setErrors([{ field: "__network__", message: "发生未知错误，请重试" }]);
      }
    } finally {
      if (seq === requestSeqRef.current) {
        setLoading(false);
      }
    }
  }

  function handleReset() {
    planVersionRef.current += 1;
    setPlan(emptyPlan());
    setRowsInput("5");
    setColsInput("6");
    setTool("start");
    setResult(null);
    setErrors([]);
  }

  // 字段级错误对应的网格格：起点/出口问题高亮对应坐标；
  // difficultCells.<索引> 错误高亮费力列表中的对应格。
  const invalidCells = useMemo(() => {
    const set = new Set<string>();
    for (const err of errors) {
      if (err.field === "start" && plan.start) {
        set.add(cellKey(plan.start.row, plan.start.col));
      } else if (err.field === "exit" && plan.exit) {
        set.add(cellKey(plan.exit.row, plan.exit.col));
      } else {
        const match = /^difficultCells\.(\d+)$/.exec(err.field);
        if (match) {
          const cell = plan.difficultCells[Number(match[1])];
          if (cell) set.add(cellKey(cell.row, cell.col));
        }
      }
    }
    return set;
  }, [errors, plan.start, plan.exit, plan.difficultCells]);

  const dimError = errors.some((e) => e.field === "rows" || e.field === "cols");

  return (
    <main className="app">
      <header>
        <h1>社区礼堂轮椅疏散路线核验器</h1>
        <p className="subtitle">
          方格边长 0.5 米 · 仅上下左右移动 · 普通移动代价 1、进入费力格代价 3 ·
          同代价时步数更少优先，再按「上 → 右 → 下 → 左」唯一确定
        </p>
      </header>

      <section className="panel panel-controls">
        <div className="dim-row">
          <label>
            行数（{MIN_DIM}-{MAX_DIM}）
            <input
              type="number"
              min={MIN_DIM}
              max={MAX_DIM}
              value={rowsInput}
              aria-label="行数"
              aria-invalid={errors.some((e) => e.field === "rows")}
              onChange={(e) => setRowsInput(e.target.value)}
            />
          </label>
          <label>
            列数（{MIN_DIM}-{MAX_DIM}）
            <input
              type="number"
              min={MIN_DIM}
              max={MAX_DIM}
              value={colsInput}
              aria-label="列数"
              aria-invalid={errors.some((e) => e.field === "cols")}
              onChange={(e) => setColsInput(e.target.value)}
            />
          </label>
          <button type="button" className="btn" onClick={applyDimensions}>
            应用尺寸
          </button>
        </div>

        <div className="tool-row" role="toolbar" aria-label="网格编辑工具">
          {TOOLS.map((t) => (
            <button
              key={t.id}
              type="button"
              className={"btn tool-btn" + (tool === t.id ? " active" : "")}
              aria-pressed={tool === t.id}
              title={t.hint}
              onClick={() => setTool(t.id)}
            >
              {t.label}
            </button>
          ))}
          <button type="button" className="btn" onClick={handleReset}>
            清空平面
          </button>
        </div>

        <div className="legend">
          <span className="legend-item"><i className="sw sw-start" />起点</span>
          <span className="legend-item"><i className="sw sw-exit" />出口</span>
          <span className="legend-item"><i className="sw sw-blocked" />阻挡（临时隔断）</span>
          <span className="legend-item"><i className="sw sw-difficult" />费力通行格（+3）</span>
          <span className="legend-item"><i className="sw sw-path" />疏散路线</span>
          <span className="legend-item"><i className="sw sw-explored" />已探索（不可达时）</span>
        </div>

        <div className="action-row">
          <button
            type="button"
            className="btn btn-primary"
            onClick={handleVerify}
            disabled={loading}
            data-testid="verify-button"
          >
            {loading ? "核验中…" : "核验最短疏散路线"}
          </button>
          <span className="plan-summary" data-testid="plan-summary">
            当前：{plan.rows} 行 × {plan.cols} 列 ·{" "}
            起点 {plan.start ? `(${plan.start.row},${plan.start.col})` : "未设置"} ·{" "}
            出口 {plan.exit ? `(${plan.exit.row},${plan.exit.col})` : "未设置"} ·{" "}
            阻挡 {plan.blocked.length} 格 · 费力 {plan.difficultCells.length} 格
          </span>
        </div>
      </section>

      {dimError && (
        <p className="dim-note" data-testid="dim-note">
          尺寸未应用，请先修正行列输入。
        </p>
      )}

      <ErrorPanel errors={errors} />

      {result && <ResultPanel result={result} />}

      <section className="grid-wrap" aria-label="平面草图">
        <GridEditor
          rows={plan.rows}
          cols={plan.cols}
          start={plan.start}
          exit={plan.exit}
          blocked={plan.blocked}
          difficultCells={plan.difficultCells}
          result={result}
          activeTool={tool}
          invalidCells={invalidCells}
          onCellClick={handleCellClick}
        />
      </section>
    </main>
  );
}

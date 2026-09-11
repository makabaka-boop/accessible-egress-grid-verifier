import type { Cell, PathResult, Tool } from "../types";
import { blockedSet, cellKey, sameCell } from "../lib/grid";

interface GridEditorProps {
  rows: number;
  cols: number;
  start: Cell | null;
  exit: Cell | null;
  blocked: Cell[];
  result: PathResult | null;
  activeTool: Tool;
  invalidCells: Set<string>;
  onCellClick: (r: number, c: number) => void;
}

const TOOL_LABELS: Record<Tool, string> = {
  start: "放置起点",
  exit: "放置出口",
  block: "放置阻挡",
  erase: "橡皮清除",
};

export function GridEditor({
  rows,
  cols,
  start,
  exit,
  blocked,
  result,
  activeTool,
  invalidCells,
  onCellClick,
}: GridEditorProps) {
  const blockedLookup = blockedSet(blocked);
  const pathCells = new Set(
    result?.reachable ? result.path.map((c) => cellKey(c.row, c.col)) : []
  );
  const exploredCells = new Set(
    result && !result.reachable
      ? result.explored.map((c) => cellKey(c.row, c.col))
      : []
  );

  const cells = [];
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const key = cellKey(r, c);
      const isStart = sameCell(start, { row: r, col: c });
      const isExit = sameCell(exit, { row: r, col: c });
      const isBlocked = blockedLookup.has(key);
      const isPath = pathCells.has(key);
      const isExplored = exploredCells.has(key);
      const isInvalid = invalidCells.has(key);

      const classes = ["cell"];
      if (isStart) classes.push("cell-start");
      if (isExit) classes.push("cell-exit");
      if (isBlocked) classes.push("cell-blocked");
      if (isPath) classes.push("cell-path");
      if (isExplored) classes.push("cell-explored");
      if (isInvalid) classes.push("cell-invalid");

      let label = "";
      if (isStart) label = "起";
      else if (isExit) label = "出";
      else if (isBlocked) label = "✕";

      cells.push(
        <button
          key={key}
          type="button"
          className={classes.join(" ")}
          data-testid={`cell-${r}-${c}`}
          data-row={r}
          data-col={c}
          aria-label={`第 ${r + 1} 行第 ${c + 1} 列（${TOOL_LABELS[activeTool]}）`}
          onClick={() => onCellClick(r, c)}
          style={{ gridRow: r + 1, gridColumn: c + 1 }}
        >
          {label}
        </button>
      );
    }
  }

  return (
    <div
      className="grid"
      role="grid"
      aria-label="礼堂平面网格"
      style={{
        gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`,
        gridTemplateRows: `repeat(${rows}, minmax(0, 1fr))`,
        ["--cols" as string]: cols,
        ["--rows" as string]: rows,
      }}
    >
      {cells}
    </div>
  );
}

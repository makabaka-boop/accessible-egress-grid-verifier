import type { PathResult } from "../types";

interface ResultPanelProps {
  result: PathResult;
}

export function ResultPanel({ result }: ResultPanelProps) {
  if (!result.reachable) {
    return (
      <section className="panel panel-unreachable" aria-live="polite" data-testid="result-unreachable">
        <h2>不可达</h2>
        <p className="verdict verdict-fail">
          当前阻挡布局下，没有任何轮椅通道能从起点到达出口。
        </p>
        <p className="result-line">
          已探索格数：
          <strong data-testid="explored-count">{result.exploredCount}</strong>
        </p>
        <p className="result-note">
          灰色格为 BFS 实际探索范围；网格上未绘制任何疏散路线。
        </p>
      </section>
    );
  }

  return (
    <section className="panel panel-ok" aria-live="polite" data-testid="result-ok">
      <h2>找到唯一最短疏散路线</h2>
      <p className="verdict verdict-ok">
        步数（不含起点）：<strong data-testid="result-steps">{result.steps}</strong>
      </p>
      <p className="result-line">
        疏散距离：
        <strong data-testid="result-distance">{result.distanceMeters}</strong> 米
        <span className="result-note">（每格 0.5 米）</span>
      </p>
      <p className="result-line">
        BFS 已探索格数：<strong>{result.exploredCount}</strong>
      </p>
      <details>
        <summary>有序坐标（起点 → 出口）</summary>
        <ol className="coord-list" data-testid="coord-list">
          {result.path.map((cell, i) => (
            <li key={`${cell.row}-${cell.col}-${i}`}>
              {i + 1}. ({cell.row}, {cell.col})
            </li>
          ))}
        </ol>
      </details>
    </section>
  );
}

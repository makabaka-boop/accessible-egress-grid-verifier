import type { PathResult } from "../types";
import { WalkTrialPanel } from "./WalkTrialPanel";

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
      <h2>找到累计通行代价最低的疏散路线</h2>
      <div className="result-stats">
        <p className="result-line">
          步数（不含起点）：<strong data-testid="result-steps">{result.steps}</strong>
        </p>
        <p className="result-line">
          疏散距离：
          <strong data-testid="result-distance">{result.distanceMeters}</strong> 米
          <span className="result-note">（每格 0.5 米）</span>
        </p>
        <p className="result-line">
          累计通行代价：
          <strong data-testid="result-cost">{result.travelCost}</strong>
          <span className="result-note">（普通移动 1，进入费力格 3）</span>
        </p>
      </div>
      <p className="result-line">
        已探索格数：<strong>{result.exploredCount}</strong>
        <span className="result-note">（不计权重的可达性搜索实际访问格数）</span>
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

      {/* 通行实测：核验通过后才能发起；反馈留在本面板，不清除上方路线 */}
      <WalkTrialPanel snapshot={result.path} />
    </section>
  );
}

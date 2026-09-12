import { useState } from "react";
import type { Cell, FieldError, WalkTrialProgress } from "../types";
import { ApiError, advanceWalkTrial, createWalkTrial } from "../lib/api";

interface WalkTrialPanelProps {
  /**成功核验返回的不可变路线快照（起点 → 出口）。 */
  snapshot: Cell[];
}

const MIN_SECONDS = 1;
const MAX_SECONDS = 3600;

function coordText(cell: Cell | null): string {
  return cell ? `(${cell.row}, ${cell.col})` : "—";
}

function segmentSummary(p: WalkTrialProgress): string {
  return p.segments.map((s) => `${s.seconds}`).join(" + ");
}

/**
 * 通行实测面板：独立于路线核验结果。
 *
 * 核验员从成功结果发起一次实测，之后逐格输入“到达下一格所用秒数”并确认；
 * 面板持续显示下一坐标、累计时间与完成进度，到达出口后锁定总耗时。
 * 所有反馈都留在本面板内，不触碰也不清除原路线。
 */
export function WalkTrialPanel({ snapshot }: WalkTrialPanelProps) {
  const [progress, setProgress] = useState<WalkTrialProgress | null>(null);
  const [secondsInput, setSecondsInput] = useState("");
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [busy, setBusy] = useState(false);

  async function handleStart() {
    setBusy(true);
    setErrors([]);
    try {
      const created = await createWalkTrial(snapshot);
      setProgress(created);
      setSecondsInput("");
    } catch (err) {
      setErrors(
        err instanceof ApiError
          ? err.fieldErrors
          : [{ field: "__network__", message: "发起实测失败，请重试" }]
      );
    } finally {
      setBusy(false);
    }
  }

  function validateSeconds(value: string): number | null {
    const trimmed = value.trim();
    if (!/^-?\d+$/.test(trimmed)) {
      setErrors([
        { field: "seconds", message: `秒数必须是 ${MIN_SECONDS} 至 ${MAX_SECONDS} 之间的整数` },
      ]);
      return null;
    }
    const seconds = Number(trimmed);
    if (seconds < MIN_SECONDS || seconds > MAX_SECONDS) {
      setErrors([
        { field: "seconds", message: `秒数必须在 ${MIN_SECONDS} 至 ${MAX_SECONDS} 之间，当前为 ${seconds}` },
      ]);
      return null;
    }
    return seconds;
  }

  async function handleAdvance() {
    if (!progress || progress.completed) return;
    const seconds = validateSeconds(secondsInput);
    if (seconds === null) return;
    setBusy(true);
    setErrors([]);
    try {
      const next = await advanceWalkTrial(progress.id, seconds);
      setProgress(next);
      setSecondsInput("");
    } catch (err) {
      setErrors(
        err instanceof ApiError
          ? err.fieldErrors
          : [{ field: "__network__", message: "推进检查点失败，请重试" }]
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      className="panel panel-walk"
      aria-live="polite"
      data-testid="walk-panel"
    >
      <h2>通行实测（轮椅逐格试走计时）</h2>

      {!progress && (
        <div className="walk-start">
          <p className="result-note">
            基于上方已核验通过的 {snapshot.length} 格路线发起一次独立实测；
            路线快照创建后不再改变，与平面后续编辑无关。
          </p>
          <button
            type="button"
            className="btn btn-primary"
            data-testid="walk-start-button"
            onClick={handleStart}
            disabled={busy}
          >
            {busy ? "发起中…" : "发起通行实测"}
          </button>
        </div>
      )}

      {progress && (
        <div className="walk-body" data-testid="walk-running">
          <p className="walk-id result-note" data-testid="walk-id">
            实测编号：{progress.id}
          </p>

          <div className="walk-stats">
            {progress.completed ? (
              <p className="result-line walk-locked" data-testid="walk-locked">
                ✅ 已到达出口，总耗时锁定：
                <strong data-testid="walk-total">{progress.totalSeconds}</strong> 秒
              </p>
            ) : (
              <>
                <p className="result-line">
                  下一坐标：
                  <strong data-testid="walk-next">{coordText(progress.nextCoordinate)}</strong>
                </p>
                <p className="result-line">
                  累计时间：
                  <strong data-testid="walk-elapsed">{progress.elapsedSeconds}</strong> 秒
                </p>
                <p className="result-line result-note">
                  剩余 {progress.remainingSteps} 格（共 {progress.totalSteps} 段）
                </p>
              </>
            )}
          </div>

          <div
            className="walk-progress"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(progress.progressPercent)}
            aria-label="通行实测完成进度"
            data-testid="walk-progressbar"
          >
            <div
              className="walk-progress-fill"
              style={{ width: `${progress.progressPercent}%` }}
            />
            <span className="walk-progress-text" data-testid="walk-percent">
              {progress.checkpoint}/{progress.totalSteps} 格 · {progress.progressPercent}%
            </span>
          </div>

          {!progress.completed && (
            <div className="walk-action">
              <label>
                到达下一格所用秒数（{MIN_SECONDS}-{MAX_SECONDS}）
                <input
                  type="number"
                  min={MIN_SECONDS}
                  max={MAX_SECONDS}
                  step={1}
                  value={secondsInput}
                  aria-label="到达下一格所用秒数"
                  aria-invalid={errors.some((e) => e.field === "seconds")}
                  data-testid="walk-seconds-input"
                  onChange={(e) => setSecondsInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") handleAdvance();
                  }}
                />
              </label>
              <button
                type="button"
                className="btn btn-primary"
                data-testid="walk-advance-button"
                onClick={handleAdvance}
                disabled={busy}
              >
                {busy ? "确认中…" : "确认到达下一格"}
              </button>
            </div>
          )}

          {progress.completed && (
            <p className="result-note" data-testid="walk-done-note">
              检查点已全部确认，不能继续推进；如需重测请编辑平面后重新核验、再发起新实测。
            </p>
          )}

          {progress.segments.length > 0 && (
            <details className="walk-segments">
              <summary>逐段秒数（{progress.segments.length} 段）</summary>
              <ol className="coord-list" data-testid="walk-segments">
                {progress.segments.map((s) => (
                  <li key={s.step}>
                    第 {s.step} 段 → ({s.row}, {s.col})：{s.seconds} 秒
                  </li>
                ))}
              </ol>
              <p className="result-note" data-testid="walk-sum">
                {segmentSummary(progress)} = {progress.elapsedSeconds} 秒
              </p>
            </details>
          )}
        </div>
      )}

      {errors.length > 0 && (
        <ul className="walk-errors" data-testid="walk-errors">
          {errors.map((err, i) => (
            <li key={`${err.field}-${i}`} data-field={err.field}>
              <strong>[{err.field}]</strong> {err.message}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

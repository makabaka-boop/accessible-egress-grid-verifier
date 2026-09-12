import { useRef, useState } from "react";
import type { Cell, FieldError, WalkTrialProgress } from "../types";
import { ApiError, advanceWalkTrial, createWalkTrial, undoWalkTrial } from "../lib/api";

interface WalkTrialPanelProps {
  /**成功核验返回的不可变路线快照（起点 → 出口）。 */
  snapshot: Cell[];
}

const MIN_SECONDS = 1;
const MAX_SECONDS = 3600;

function coordText(cell: Cell | null): string {
  return cell ? `(${cell.row}, ${cell.col})` : "—";
}

function coordListText(cells: Cell[]): string {
  return cells.length > 0 ? cells.map((c) => `(${c.row}, ${c.col})`).join("、") : "无";
}

function segmentSummary(p: WalkTrialProgress): string {
  return p.segments.map((s) => `${s.seconds}`).join(" + ");
}

/**
 * 通行实测面板：独立于路线核验结果。
 *
 * 核验员从成功结果发起一次实测，发起前可选填“单段目标秒数”（1–3600 的
 * 整数）：设定后每段按“秒数大于目标 → 超时，否则达标”逐格判定，面板
 * 即时汇总两类段数与对应坐标；留空则不判定，行为与旧版一致。
 * 之后逐格输入“到达下一格所用秒数”并确认；面板持续显示下一坐标、累计
 * 时间与完成进度，到达出口后锁定总耗时。输错某段秒数时可「撤回上一段」
 * （进行中与已完成状态都可用），回退检查点后按正确秒数重新确认，
 * 不必丢弃已核验路线和整次实测。
 * 所有反馈都留在本面板内，不触碰也不清除原路线。
 */
export function WalkTrialPanel({ snapshot }: WalkTrialPanelProps) {
  const [progress, setProgress] = useState<WalkTrialProgress | null>(null);
  const [secondsInput, setSecondsInput] = useState("");
  const [targetInput, setTargetInput] = useState("");
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [busy, setBusy] = useState(false);
  // busy 的状态更新在同一事件轮内尚未刷新；ref 用于同步拦截连按回车。
  const requestInFlight = useRef(false);
  // 记录请求发出后用户是否又编辑过秒数，避免响应返回时清空尚未提交的下一段。
  const secondsDraftDirty = useRef(false);

  function isValidSecondsInput(value: string): boolean {
    const trimmed = value.trim();
    if (!/^-?\d+$/.test(trimmed)) return false;
    const seconds = Number(trimmed);
    return seconds >= MIN_SECONDS && seconds <= MAX_SECONDS;
  }

  function dismissFieldError(field: string) {
    setErrors((prev) => prev.filter((err) => err.field !== field));
  }

  /**解析可选目标输入：空 → 不携带；非法 → 面板内报错且不发起请求。 */
  function parseTargetInput(): { ok: true; target?: number } | { ok: false; error: FieldError } {
    const trimmed = targetInput.trim();
    if (trimmed === "") {
      return { ok: true };
    }
    if (!/^-?\d+$/.test(trimmed)) {
      return {
        ok: false,
        error: { field: "targetSeconds", message: `目标秒数必须是 ${MIN_SECONDS} 至 ${MAX_SECONDS} 之间的整数` },
      };
    }
    const target = Number(trimmed);
    if (target < MIN_SECONDS || target > MAX_SECONDS) {
      return {
        ok: false,
        error: { field: "targetSeconds", message: `目标秒数必须在 ${MIN_SECONDS} 至 ${MAX_SECONDS} 之间，当前为 ${target}` },
      };
    }
    return { ok: true, target };
  }

  async function handleStart() {
    if (requestInFlight.current) return;
    const parsed = parseTargetInput();
    if (!parsed.ok) {
      setErrors([parsed.error]);
      return;
    }
    requestInFlight.current = true;
    setBusy(true);
    setErrors([]);
    try {
      const created = await createWalkTrial(snapshot, parsed.target);
      setProgress(created);
      setSecondsInput("");
    } catch (err) {
      // 创建失败（含目标值被服务端拒绝）：进度不建立，路线快照与
      // 用户已填写的目标值都保留，便于现场修正后重试。
      setErrors(
        err instanceof ApiError
          ? err.fieldErrors
          : [{ field: "__network__", message: "发起实测失败，请重试" }]
      );
    } finally {
      requestInFlight.current = false;
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
    if (requestInFlight.current || !progress || progress.completed) return;
    const seconds = validateSeconds(secondsInput);
    if (seconds === null) return;

    requestInFlight.current = true;
    secondsDraftDirty.current = false;
    setBusy(true);
    setErrors([]);
    try {
      const next = await advanceWalkTrial(progress.id, seconds);
      setProgress(next);
      // 等待期间若已预填下一段，响应到达时必须保留该未提交内容。
      if (!secondsDraftDirty.current) {
        setSecondsInput("");
      }
    } catch (err) {
      setErrors(
        err instanceof ApiError
          ? err.fieldErrors
          : [{ field: "__network__", message: "推进检查点失败，请重试" }]
      );
    } finally {
      requestInFlight.current = false;
      setBusy(false);
    }
  }

  async function handleUndo() {
    if (requestInFlight.current || !progress) return;
    requestInFlight.current = true;
    setBusy(true);
    setErrors([]);
    try {
      const next = await undoWalkTrial(progress.id);
      // 撤回成功：进度回退到上一格，面板据响应重新展示下一坐标与秒数
      // 输入框；已填写的秒数草稿保留，可直接修正后重新确认。
      setProgress(next);
    } catch (err) {
      // 撤回被拒（尚无已确认分段 / 编号不存在）：字段级反馈留在面板内，
      // 进度、原路线与当前输入都不变。
      setErrors(
        err instanceof ApiError
          ? err.fieldErrors
          : [{ field: "__network__", message: "撤回上一段失败，请重试" }]
      );
    } finally {
      requestInFlight.current = false;
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
          <label className="walk-target-label">
            单段目标秒数（可选，{MIN_SECONDS}-{MAX_SECONDS}）
            <input
              type="text"
              inputMode="numeric"
              value={targetInput}
              aria-label="单段目标秒数"
              aria-invalid={errors.some((e) => e.field === "targetSeconds")}
              data-testid="walk-target-input"
              placeholder="留空则不判定"
              onChange={(e) => {
                const value = e.target.value;
                setTargetInput(value);
                if (value.trim() === "" || isValidSecondsInput(value)) {
                  dismissFieldError("targetSeconds");
                }
              }}
            />
          </label>
          <p className="result-note">
            填写后，超过该秒数的分段将被标记为“超时”，其余为“达标”，并实时汇总。
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
            {progress.targetSeconds !== null && (
              <p className="result-line">
                单段目标：
                <strong data-testid="walk-target-display">{progress.targetSeconds}</strong> 秒
                <span className="result-note">（超过即判超时）</span>
              </p>
            )}
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
                  剩余 {progress.remainingSteps} 段（共 {progress.totalSteps} 段）
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
              已确认 {progress.checkpoint}/{progress.totalSteps} 段 · {progress.progressPercent}%
            </span>
          </div>

          {progress.verdictSummary && (
            <div className="walk-verdicts" data-testid="walk-verdict-summary">
              <p className="result-line">
                分段判定：
                <strong data-testid="walk-ontarget-count">
                  达标 {progress.verdictSummary.onTargetCount} 段
                </strong>
                {" · "}
                <strong data-testid="walk-overtime-count">
                  超时 {progress.verdictSummary.overtimeCount} 段
                </strong>
              </p>
              <p className="result-line walk-verdict-overtime">
                超时坐标：
                <span data-testid="walk-overtime-coords">
                  {coordListText(progress.verdictSummary.overtimeCoordinates)}
                </span>
              </p>
              <p className="result-line">
                达标坐标：
                <span data-testid="walk-ontarget-coords">
                  {coordListText(progress.verdictSummary.onTargetCoordinates)}
                </span>
              </p>
            </div>
          )}

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
                  onChange={(e) => {
                    const value = e.target.value;
                    setSecondsInput(value);
                    secondsDraftDirty.current = requestInFlight.current;
                    if (isValidSecondsInput(value)) {
                      dismissFieldError("seconds");
                    }
                  }}
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
              检查点已全部确认，总耗时已锁定；若末段秒数有误，可撤回上一段后重新确认，
              或编辑平面重新核验、再发起新实测。
            </p>
          )}

          <div className="walk-undo-row">
            <button
              type="button"
              className="btn"
              data-testid="walk-undo-button"
              onClick={handleUndo}
              disabled={busy}
            >
              {busy ? "处理中…" : "撤回上一段"}
            </button>
            <span className="result-note">
              输错某段秒数时撤回最后一次推进，再按正确秒数重新确认；路线快照与实测编号不变。
            </span>
          </div>

          {progress.segments.length > 0 && (
            <details className="walk-segments">
              <summary>逐段秒数（{progress.segments.length} 段）</summary>
              <ol className="coord-list" data-testid="walk-segments">
                {progress.segments.map((s) => (
                  <li key={s.step} data-verdict={s.verdict ?? undefined}>
                    第 {s.step} 段 → ({s.row}, {s.col})：{s.seconds} 秒
                    {s.verdict && (
                      <strong
                        className={
                          s.verdict === "overtime"
                            ? "walk-badge walk-badge-overtime"
                            : "walk-badge walk-badge-ontarget"
                        }
                        data-testid={`walk-segment-verdict-${s.step}`}
                      >
                        {s.verdict === "overtime" ? "超时" : "达标"}
                      </strong>
                    )}
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

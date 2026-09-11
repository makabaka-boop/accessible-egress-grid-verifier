import type { FieldError } from "../types";

interface ErrorPanelProps {
  errors: FieldError[];
}

const FIELD_HINTS: Record<string, string> = {
  rows: "请检查“行数”输入",
  cols: "请检查“列数”输入",
  start: "请检查网格上的起点",
  exit: "请检查网格上的出口",
  blocked: "请检查网格上的阻挡格",
};

export function ErrorPanel({ errors }: ErrorPanelProps) {
  if (errors.length === 0) return null;
  return (
    <section className="panel panel-error" aria-live="assertive" data-testid="error-panel">
      <h2>核验未通过（本次请求失败，未生成路线）</h2>
      <ul>
        {errors.map((err, i) => {
          const hint = FIELD_HINTS[err.field] || "请检查请求内容";
          return (
            <li key={`${err.field}-${i}`} data-field={err.field}>
              <strong data-testid="error-field">[{err.field}]</strong> {err.message}
              <span className="error-hint"> → {hint}</span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

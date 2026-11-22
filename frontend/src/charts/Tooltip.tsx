// Chart tooltip: value first, label second; series keyed with a short line, not a box. All text is inserted by React as text nodes.
import type { ReactNode } from "react";

export interface TipRow { color?: string; label: string; value: string }

export function Tooltip({ x, y, title, rows, children }: { x: number; y: number; title?: string; rows?: TipRow[]; children?: ReactNode }) {
  return (
    <div className="tooltip" style={{ left: x, top: y }} role="status">
      {rows?.map((r) => (
        <div key={r.label}>
          <div className="tt-value">{r.value}</div>
          <div className="tt-row">
            {r.color && <span className="tt-key" style={{ background: r.color }} />}
            <span>{r.label}</span>
          </div>
        </div>
      ))}
      {children}
      {title && <div className="muted" style={{ marginTop: 4 }}>{title}</div>}
    </div>
  );
}

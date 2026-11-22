// Every chart gets a "table view" that shows its values as an accessible table (hover tooltips enhance, they are never the only way in).
import { useState, type ReactNode } from "react";

export function TableToggle({ columns, rows, children }: { columns: { label: string; num?: boolean }[]; rows: (string | number)[][]; children: ReactNode }) {
  const [table, setTable] = useState(false);
  return (
    <div>
      <div className="row" style={{ justifyContent: "flex-end", marginTop: -8, marginBottom: 6 }}>
        <button className="btn ghost small table-toggle" onClick={() => setTable((t) => !t)} aria-pressed={table}>
          {table ? "Show chart" : "Show table"}
        </button>
      </div>
      {table ? (
        <div className="table-wrap">
          <table className="data-table">
            <thead><tr>{columns.map((c) => <th key={c.label} className={c.num ? "num" : ""}>{c.label}</th>)}</tr></thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>{r.map((v, j) => <td key={j} className={columns[j]?.num ? "num" : ""}>{v}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : children}
    </div>
  );
}

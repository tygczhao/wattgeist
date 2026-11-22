// Tariff prices vs the average day: two measures with different units (£/kWh and W), so two stacked panels share the x-axis instead of a dual y-axis.
import { useState } from "react";
import { niceTicks, watts } from "../lib/format";
import { useWidth } from "./useSize";

export interface PriceSeries { id: string; name: string; color: string; prices: number[] }

export function PriceProfile({ series, slots, weekday, weekend, currency }: {
  series: PriceSeries[]; slots: string[]; weekday: (number | null)[]; weekend: (number | null)[]; currency: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  // Each panel reserves 22px at the top for its unit label so it never overlaps the top tick
  const m = { top: 22, right: 16, bottom: 22, left: 52 };
  const iw = Math.max(10, width - m.left - m.right);
  const h1 = 160;
  const h2 = 140;
  const n = 48;
  const x = (i: number) => m.left + (i / (n - 1)) * iw;
  const sym = currency === "GBP" ? "£" : currency === "USD" ? "$" : "";

  const pMax = Math.max(...series.flatMap((s) => s.prices), 0.1);
  const pMin = Math.min(0, ...series.flatMap((s) => s.prices));
  const pTicks = niceTicks(pMax, 3);
  const pTop = pTicks[pTicks.length - 1];
  const py = (v: number) => m.top + (h1 - m.top - 8) * (1 - (v - pMin) / (pTop - pMin));

  // Usage curve: 30-minute data has 48 points; hourly data has 24, repeated per half hour to share the x-axis
  const expand = (arr: (number | null)[]) => (arr.length === 24 ? arr.flatMap((v) => [v, v]) : arr);
  const wd = expand(weekday);
  const we = expand(weekend);
  const uMax = Math.max(...wd.map((v) => v ?? 0), ...we.map((v) => v ?? 0), 10);
  const uTicks = niceTicks(uMax, 3);
  const uTop = uTicks[uTicks.length - 1];
  const uy = (v: number) => h1 + m.top + (h2 - m.top - m.bottom) * (1 - v / uTop);
  const line = (arr: (number | null)[], f: (v: number) => number) =>
    arr.map((v, i) => (v == null ? "" : `${i && arr[i - 1] != null ? "L" : "M"}${x(i).toFixed(1)},${f(v).toFixed(1)}`)).join("");
  const step = (prices: number[]) =>
    prices.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${py(v).toFixed(1)}${i < n - 1 ? `H${x(i + 1).toFixed(1)}` : ""}`).join("");

  const total = h1 + h2;
  return (
    <div className="chart" ref={ref}>
      <svg width={width} height={total} role="img" aria-label="Tariff prices through the day above average household power">
        {pTicks.map((t) => (
          <g key={`p${t}`}>
            <line className="grid-line" x1={m.left} x2={m.left + iw} y1={py(t)} y2={py(t)} />
            <text x={m.left - 8} y={py(t) + 4} textAnchor="end">{`${sym}${t.toFixed(2)}`}</text>
          </g>
        ))}
        <text x={0} y={10}>{`${sym || currency} per kWh`}</text>
        {series.map((s) => <path key={s.id} d={step(s.prices)} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" />)}

        {uTicks.map((t) => (
          <g key={`u${t}`}>
            <line className="grid-line" x1={m.left} x2={m.left + iw} y1={uy(t)} y2={uy(t)} />
            <text x={m.left - 8} y={uy(t) + 4} textAnchor="end">{t}</text>
          </g>
        ))}
        <text x={0} y={h1 + 10}>Average power, W</text>
        <path d={`${line(wd, uy)}`} fill="none" stroke="var(--text-2)" strokeWidth={2} />
        <path d={`${line(we, uy)}`} fill="none" stroke="var(--muted)" strokeWidth={2} strokeOpacity={0.7} />
        <line className="axis-line" x1={m.left} x2={m.left + iw} y1={uy(0)} y2={uy(0)} />
        {[0, 12, 24, 36, 47].map((i) => (
          <text key={i} x={x(i)} y={total - 4} textAnchor={i === 47 ? "end" : i === 0 ? "start" : "middle"}>{i === 47 ? "24:00" : slots[i] ?? ""}</text>
        ))}
        {hover != null && <line x1={x(hover)} x2={x(hover)} y1={m.top} y2={uy(0)} stroke="var(--axis)" pointerEvents="none" />}
        <rect x={m.left} y={m.top} width={iw} height={uy(0) - m.top} fill="transparent"
          onPointerMove={(e) => {
            const r = e.currentTarget.getBoundingClientRect();
            setHover(Math.max(0, Math.min(n - 1, Math.round(((e.clientX - r.left) / r.width) * (n - 1)))));
          }}
          onPointerLeave={() => setHover(null)} />
      </svg>
      {hover != null && (
        <div className="tooltip" style={{ left: x(hover), top: m.top + 8, transform: "translate(-50%, 0)" }}>
          <div className="muted" style={{ marginBottom: 4 }}>{`${String(Math.floor(hover / 2)).padStart(2, "0")}:${hover % 2 ? "30" : "00"}`}</div>
          {series.map((s) => (
            <div className="tt-row" key={s.id}>
              <span className="tt-key" style={{ background: s.color }} />
              <span className="tt-value" style={{ fontSize: 13 }}>{`${sym}${s.prices[hover].toFixed(3)}`}</span>
              <span>{s.name}</span>
            </div>
          ))}
          <div className="tt-row"><span className="tt-key" style={{ background: "var(--text-2)" }} /><span className="tt-value" style={{ fontSize: 13 }}>{watts(wd[hover])}</span><span>Weekday use</span></div>
        </div>
      )}
      <div className="legend">
        {series.map((s) => <span key={s.id}><i className="key" style={{ background: s.color }} />{s.name}</span>)}
        <span><i className="key" style={{ background: "var(--text-2)" }} />Your weekday use</span>
        <span><i className="key" style={{ background: "var(--muted)" }} />Your weekend use</span>
      </div>
    </div>
  );
}

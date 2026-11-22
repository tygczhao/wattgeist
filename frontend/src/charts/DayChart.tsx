// Power through one day as columns (one series, orange), for looking at what happened on a haunted night.
import { useState } from "react";
import { niceTicks, watts } from "../lib/format";
import { Tooltip } from "./Tooltip";
import { useWidth } from "./useSize";

export function DayChart({ slots, values, floor }: { slots: string[]; values: (number | null)[]; floor?: number }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const height = 200;
  const m = { top: 24, right: 56, bottom: 24, left: 48 };
  const iw = Math.max(10, width - m.left - m.right);
  const ih = height - m.top - m.bottom;
  const vmax = Math.max(...values.map((v) => v ?? 0), floor ?? 0, 10);
  const ticks = niceTicks(vmax, 4);
  const max = ticks[ticks.length - 1];
  const band = iw / Math.max(1, values.length);
  const bw = Math.min(24, Math.max(2, band - 2));
  const y = (v: number) => m.top + ih - (v / max) * ih;

  // 4px rounded data end, square baseline end: columns are drawn as paths
  const bar = (i: number, v: number) => {
    const x0 = m.left + i * band + (band - bw) / 2;
    const top = y(v);
    const base = y(0);
    const r = Math.min(4, bw / 2, (base - top) / 2);
    return `M${x0},${base}V${top + r}Q${x0},${top} ${x0 + r},${top}H${x0 + bw - r}Q${x0 + bw},${top} ${x0 + bw},${top + r}V${base}Z`;
  };

  return (
    <div className="chart" ref={ref}>
      <svg width={width} height={height} role="img" aria-label="Power through the day">
        {ticks.map((t) => (
          <g key={t}>
            <line className="grid-line" x1={m.left} x2={m.left + iw} y1={y(t)} y2={y(t)} />
            <text x={m.left - 8} y={y(t) + 4} textAnchor="end">{t}</text>
          </g>
        ))}
        <text x={0} y={10}>W</text>
        {values.map((v, i) => v != null && v > 0 ? (
          <path key={i} d={bar(i, v)} fill="var(--s1)" opacity={hover == null || hover === i ? 1 : 0.55} />
        ) : null)}
        <line className="axis-line" x1={m.left} x2={m.left + iw} y1={y(0)} y2={y(0)} />
        {slots.map((s, i) => (s.endsWith(":00") && Number(s.slice(0, 2)) % 6 === 0 ? (
          <text key={s} x={m.left + i * band} y={height - 6}>{s}</text>
        ) : null))}
        {floor != null && (
          <>
            <line x1={m.left} x2={m.left + iw} y1={y(floor)} y2={y(floor)} stroke="var(--text-2)" strokeOpacity={0.5} />
            <text className="label-2" x={m.left + iw + 8} y={y(floor) + 4}>{watts(floor)}</text>
            <text x={m.left + iw + 8} y={y(floor) + 18}>typical floor</text>
          </>
        )}
        {values.map((_, i) => (
          <rect key={i} x={m.left + i * band} y={m.top} width={band} height={ih} fill="transparent"
            onPointerEnter={() => setHover(i)} onPointerLeave={() => setHover(null)} />
        ))}
      </svg>
      {hover != null && values[hover] != null && (
        <Tooltip x={m.left + (hover + 0.5) * band} y={y(values[hover] ?? 0)} title={slots[hover]}
          rows={[{ label: "Average power", value: watts(values[hover]) }]} />
      )}
    </div>
  );
}

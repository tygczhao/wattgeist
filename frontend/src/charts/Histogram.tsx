// Always-on distribution of the London sample (one-series histogram) + a marker for this home. Adjacent bars are separated by a 2px surface gap.
import { watts } from "../lib/format";
import { useWidth } from "./useSize";

export function Histogram({ edges, counts, value, median }: { edges: number[]; counts: number[]; value: number; median: number }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const height = 150;
  const m = { top: 26, right: 12, bottom: 22, left: 12 };
  const iw = Math.max(10, width - m.left - m.right);
  const ih = height - m.top - m.bottom;
  const max = Math.max(...counts, 1);
  const lo = edges[0];
  const hi = edges[edges.length - 1];
  const x = (w: number) => m.left + ((Math.min(Math.max(w, lo), hi) - lo) / (hi - lo)) * iw;
  const band = iw / counts.length;
  const clamp = value >= hi;
  return (
    <div className="chart" ref={ref}>
      <svg width={width} height={height} role="img" aria-label={`Your always-on load ${watts(value)} compared with London homes`}>
        {counts.map((c, i) => {
          const h = (c / max) * ih;
          return <rect key={i} x={m.left + i * band + 1} y={m.top + ih - h} width={Math.max(1, band - 2)} height={h} rx={2}
            fill="var(--s2)" opacity={0.55} />;
        })}
        <line className="axis-line" x1={m.left} x2={m.left + iw} y1={m.top + ih} y2={m.top + ih} />
        {[0, 100, 200, 300, 400, 500, 600].filter((t) => t <= hi).map((t) => (
          <text key={t} x={x(t)} y={height - 6} textAnchor="middle">{t}</text>
        ))}
        <line x1={x(median)} x2={x(median)} y1={m.top - 4} y2={m.top + ih} stroke="var(--text-2)" strokeOpacity={0.6} />
        <text className="label-2" x={x(median)} y={m.top - 8} textAnchor="middle">{`London median ${watts(median)}`}</text>
        <line x1={x(value)} x2={x(value)} y1={m.top - 4} y2={m.top + ih} stroke="var(--s1)" strokeWidth={2} />
        <circle cx={x(value)} cy={m.top + ih} r={5} fill="var(--s1)" stroke="var(--card)" strokeWidth={2} />
        <text className="label-strong" x={Math.min(x(value), m.left + iw - 30)} y={m.top + 12} textAnchor={x(value) > m.left + iw - 80 ? "end" : "start"} dx={x(value) > m.left + iw - 80 ? -6 : 6}>
          {`You ${clamp ? "≥" : ""}${watts(value)}`}
        </text>
      </svg>
    </div>
  );
}

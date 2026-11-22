// Daily floor line (day-by-day always-on load) + local baseline, with haunted nights as red end dots. One y-axis (W).
import { useMemo, useState } from "react";
import { niceTicks, shortDate, watts } from "../lib/format";
import { Tooltip } from "./Tooltip";
import { useWidth } from "./useSize";

interface Point { date: string; floor_w: number; baseline_w: number }

export function FloorChart({ data, haunted, alwaysOn, onPick }: {
  data: Point[]; haunted: Set<string>; alwaysOn: number; onPick?: (date: string) => void;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const height = 240;
  const m = { top: 24, right: 64, bottom: 26, left: 48 };
  const iw = Math.max(10, width - m.left - m.right);
  const ih = height - m.top - m.bottom;

  const { ticks, max, x, y, linePath, basePath, months } = useMemo(() => {
    const vmax = Math.max(...data.map((d) => Math.max(d.floor_w, d.baseline_w)), alwaysOn * 1.2, 10);
    const ticks = niceTicks(vmax, 4);
    const max = ticks[ticks.length - 1];
    const x = (i: number) => m.left + (data.length <= 1 ? 0 : (i / (data.length - 1)) * iw);
    const y = (v: number) => m.top + ih - (v / max) * ih;
    const path = (key: "floor_w" | "baseline_w") =>
      data.map((d, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(d[key]).toFixed(1)}`).join("");
    // Month ticks: the first point of each month
    const months: { i: number; label: string }[] = [];
    let last = "";
    data.forEach((d, i) => {
      const ym = d.date.slice(0, 7);
      if (ym !== last) {
        last = ym;
        months.push({ i, label: new Date(`${d.date}T12:00:00Z`).toLocaleDateString("en-GB", { month: "short", timeZone: "UTC" }) });
      }
    });
    return { ticks, max, x, y, linePath: path("floor_w"), basePath: path("baseline_w"), months };
  }, [data, iw, ih, alwaysOn, m.left, m.top]);

  if (!data.length) return <div className="empty">No complete days yet.</div>;
  // Month ticks at least 32px apart; a first month covering only a few days gives way to the next one
  const shownMonths = months.filter((mo, k) => {
    const next = months[k + 1];
    if (k === 0 && next && x(next.i) - x(mo.i) < 32) return false;
    return true;
  }).filter((mo, k, arr) => k === 0 || x(mo.i) - x(arr[k - 1].i) >= 32);

  function onMove(e: React.PointerEvent<SVGRectElement>) {
    const rect = (e.currentTarget as SVGRectElement).getBoundingClientRect();
    const px = e.clientX - rect.left;
    const i = Math.round((px / rect.width) * (data.length - 1));
    setHover(Math.max(0, Math.min(data.length - 1, i)));
  }
  const h = hover != null ? data[hover] : null;

  return (
    <div className="chart" ref={ref}>
      <svg width={width} height={height} role="img" aria-label={`Daily always-on floor, typical ${watts(alwaysOn)}`}>
        {ticks.map((t) => (
          <g key={t}>
            <line className="grid-line" x1={m.left} x2={m.left + iw} y1={y(t)} y2={y(t)} />
            <text x={m.left - 8} y={y(t) + 4} textAnchor="end">{t}</text>
          </g>
        ))}
        <text x={0} y={10}>W</text>
        <line className="axis-line" x1={m.left} x2={m.left + iw} y1={y(0)} y2={y(0)} />
        {shownMonths.map((mo) => (
          <text key={mo.i} x={x(mo.i)} y={height - 8} textAnchor="start">{mo.label}</text>
        ))}
        <path d={basePath} fill="none" stroke="var(--muted)" strokeWidth={1.5} strokeOpacity={0.6} />
        <path d={linePath} fill="none" stroke="var(--s1)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        {data.map((d, i) => haunted.has(d.date) ? (
          <circle key={d.date} cx={x(i)} cy={y(d.floor_w)} r={4.5} fill="var(--s8)" stroke="var(--card)" strokeWidth={2} />
        ) : null)}
        {/* Direct label at the right end: the median always-on load */}
        <line x1={m.left} x2={m.left + iw} y1={y(alwaysOn)} y2={y(alwaysOn)} stroke="var(--text-2)" strokeOpacity={0.35} />
        <text className="label-strong" x={m.left + iw + 8} y={y(alwaysOn) + 4}>{watts(alwaysOn)}</text>
        <text x={m.left + iw + 8} y={y(alwaysOn) + 18}>typical</text>
        {h && hover != null && (
          <g pointerEvents="none">
            <line x1={x(hover)} x2={x(hover)} y1={m.top} y2={m.top + ih} stroke="var(--axis)" />
            <circle cx={x(hover)} cy={y(h.floor_w)} r={4} fill="var(--s1)" stroke="var(--card)" strokeWidth={2} />
          </g>
        )}
        <rect
          x={m.left} y={m.top} width={iw} height={ih} fill="transparent"
          onPointerMove={onMove} onPointerLeave={() => setHover(null)}
          onClick={() => h && onPick?.(h.date)} style={{ cursor: onPick ? "pointer" : "default" }}
        />
        <title>{`Max ${max} W`}</title>
      </svg>
      {h && hover != null && (
        <Tooltip
          x={x(hover)} y={y(h.floor_w)}
          title={`${shortDate(h.date)}${haunted.has(h.date) ? " · haunted" : ""}`}
          rows={[
            { color: "var(--s1)", label: "Lowest power that day", value: watts(h.floor_w) },
            { color: "var(--muted)", label: "Local baseline", value: watts(h.baseline_w) },
          ]}
        />
      )}
      <div className="legend">
        <span><i className="key" style={{ background: "var(--s1)" }} />Daily floor</span>
        <span><i className="key" style={{ background: "var(--muted)" }} />29-day baseline</span>
        <span><i className="swatch" style={{ background: "var(--s8)", borderRadius: "50%" }} />Haunted night</span>
      </div>
    </div>
  );
}

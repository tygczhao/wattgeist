// Calendar heatmap: date across, time of day down, colour = average power (one orange sequential ramp, near zero recedes into the surface).
// 365 x 48 cells drawn on a canvas; hover maps the pointer position back to a cell.
import { useEffect, useMemo, useRef, useState } from "react";
import { shortDate, watts } from "../lib/format";
import type { Heatmap as HeatmapData } from "../lib/types";
import { Tooltip } from "./Tooltip";
import { useWidth } from "./useSize";

// Orange sequential ramp (dark surface): from near-surface to bright orange, one hue, monotonic lightness
const RAMP_DARK = ["#221a1e", "#3a2416", "#5c3218", "#83411b", "#a9521f", "#d06325", "#ec7a35", "#f59a5c", "#fbbd8c"];
const RAMP_LIGHT = ["#fbf3ec", "#f9dcc6", "#f5bf98", "#f0a06d", "#ea8146", "#d9652a", "#b84f1d", "#913c15", "#6b2c10"];

export function Heatmap({ data, highlight }: { data: HeatmapData; highlight?: string | null }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const [hover, setHover] = useState<{ d: number; s: number } | null>(null);
  const light = document.documentElement.dataset.theme === "light";
  const ramp = light ? RAMP_LIGHT : RAMP_DARK;
  const m = { top: 8, right: 8, bottom: 24, left: 44 };
  const height = 260;
  const iw = Math.max(10, width - m.left - m.right);
  const ih = height - m.top - m.bottom;
  const nd = data.dates.length;
  const ns = data.slots.length;

  // Cap the ramp at the 98th percentile so a few spikes do not push every other cell into the darkest step
  const vmax = useMemo(() => {
    const all = data.watts.flat().filter((v): v is number => v != null).sort((a, b) => a - b);
    return all.length ? Math.max(50, all[Math.floor(all.length * 0.98)]) : 1000;
  }, [data]);
  const color = (v: number | null) => {
    if (v == null) return "transparent";
    const t = Math.min(1, Math.sqrt(Math.max(0, v) / vmax));
    return ramp[Math.min(ramp.length - 1, Math.floor(t * (ramp.length - 1) + 0.5))];
  };

  useEffect(() => {
    const c = canvas.current;
    if (!c) return;
    const dpr = window.devicePixelRatio || 1;
    c.width = Math.round(iw * dpr);
    c.height = Math.round(ih * dpr);
    const ctx = c.getContext("2d")!;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, iw, ih);
    const cw = iw / nd;
    const ch = ih / ns;
    for (let d = 0; d < nd; d++) {
      for (let s = 0; s < ns; s++) {
        const v = data.watts[d][s];
        if (v == null) continue;
        ctx.fillStyle = color(v);
        ctx.fillRect(d * cw, s * ch, Math.ceil(cw), Math.ceil(ch));
      }
    }
    if (highlight) {
      const d = data.dates.indexOf(highlight);
      if (d >= 0) {
        ctx.strokeStyle = light ? "#17141f" : "#f2eee6";
        ctx.lineWidth = 1.5;
        ctx.strokeRect(d * cw - 1, 0.75, cw + 2, ih - 1.5);
      }
    }
  }, [data, iw, ih, nd, ns, highlight, light]); // eslint-disable-line react-hooks/exhaustive-deps

  const hourTicks = [0, 6, 12, 18].map((h) => ({ h, s: Math.round((h * 60) / (1440 / ns)) }));
  const monthTicks: { d: number; label: string }[] = [];
  let last = "";
  data.dates.forEach((date, d) => {
    const ym = date.slice(0, 7);
    if (ym !== last) {
      last = ym;
      monthTicks.push({ d, label: new Date(`${date}T12:00:00Z`).toLocaleDateString("en-GB", { month: "short", timeZone: "UTC" }) });
    }
  });

  function onMove(e: React.PointerEvent<HTMLCanvasElement>) {
    const r = e.currentTarget.getBoundingClientRect();
    const d = Math.floor(((e.clientX - r.left) / r.width) * nd);
    const s = Math.floor(((e.clientY - r.top) / r.height) * ns);
    if (d >= 0 && d < nd && s >= 0 && s < ns) setHover({ d, s });
  }
  const hv = hover ? data.watts[hover.d][hover.s] : null;

  return (
    <div className="chart" ref={ref} style={{ height: height + 34 }}>
      <svg width={width} height={height} style={{ position: "absolute", inset: 0 }} aria-hidden="true">
        {hourTicks.map((t) => (
          <text key={t.h} x={m.left - 8} y={m.top + (t.s / ns) * ih + 4} textAnchor="end">{`${String(t.h).padStart(2, "0")}:00`}</text>
        ))}
        {spacedTicks(monthTicks, (t) => m.left + (t.d / nd) * iw, 30).map((t) => (
          <text key={t.d} x={m.left + (t.d / nd) * iw} y={height - 6}>{t.label}</text>
        ))}
      </svg>
      <canvas
        ref={canvas}
        role="img"
        aria-label="Average power by day and time of day"
        style={{ position: "absolute", left: m.left, top: m.top, width: iw, height: ih, borderRadius: 4, cursor: "crosshair" }}
        onPointerMove={onMove}
        onPointerLeave={() => setHover(null)}
      />
      {hover && (
        <Tooltip
          x={m.left + ((hover.d + 0.5) / nd) * iw}
          y={m.top + (hover.s / ns) * ih}
          title={`${shortDate(data.dates[hover.d])} · ${data.slots[hover.s]}`}
          rows={[{ label: "Average power", value: hv == null ? "No reading" : watts(hv) }]}
        />
      )}
      <div className="legend" style={{ position: "absolute", left: m.left, top: height + 4, alignItems: "center" }}>
        <span>0 W</span>
        <span style={{ display: "inline-flex", gap: 0 }}>
          {ramp.map((c) => <i key={c} style={{ width: 18, height: 10, background: c, display: "inline-block" }} />)}
        </span>
        <span>{watts(vmax)}+</span>
      </div>
    </div>
  );
}

/** Keep only ticks at least minGap pixels apart; a first month of only a few days gives way to the next full month. */
function spacedTicks<T>(ticks: T[], pos: (t: T) => number, minGap: number): T[] {
  const out: T[] = [];
  for (let i = 0; i < ticks.length; i++) {
    const x = pos(ticks[i]);
    const next = ticks[i + 1];
    if (next && pos(next) - x < minGap && i === 0) continue;
    if (out.length && x - pos(out[out.length - 1]) < minGap) continue;
    out.push(ticks[i]);
  }
  return out;
}

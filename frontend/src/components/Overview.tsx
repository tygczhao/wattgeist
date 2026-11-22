// Overview tab: the hero figure is the always-on load (the one big number on this screen), then KPIs, the London comparison and the heatmap.
import { useEffect, useState } from "react";
import { Heatmap } from "../charts/Heatmap";
import { Histogram } from "../charts/Histogram";
import { api } from "../lib/api";
import { kwh, money, pct, shortDate, watts } from "../lib/format";
import type { Heatmap as HeatmapData, Overview as OverviewData } from "../lib/types";

export function Overview({ data, onHunt }: { data: OverviewData; onHunt: () => void }) {
  const [heat, setHeat] = useState<HeatmapData | null>(null);
  const id = data.household.id;
  useEffect(() => {
    let live = true;
    api.heatmap(id).then((h) => live && setHeat(h)).catch(() => live && setHeat(null));
    return () => { live = false; };
  }, [id]);

  const ao = data.always_on;
  const s = data.summary;
  const b = data.benchmark;
  return (
    <div className="stack">
      {ao ? (
        <section className="hero">
          <div>
            <div className="hero-kicker">Always-on load: what this home draws when nobody is using anything</div>
            <div><span className="hero-figure">{Math.round(ao.watts)}</span><span className="hero-unit">W</span></div>
            <p className="hero-line">
              That never-sleeping draw adds up to <strong>{kwh(ao.annual_kwh, 0)}</strong> a year, about{" "}
              <strong>{money(ao.annual_cost, ao.currency ?? "GBP")}</strong> at {money(ao.price_used, ao.currency ?? "GBP")}/kWh
              and <strong>{pct(ao.share)}</strong> of everything this home uses.
            </p>
            <div className="row wrap" style={{ marginTop: 16 }}>
              <button className="btn primary" onClick={onHunt}>Hunt the vampires</button>
              {ao.haunted_nights > 0 && <span className="badge"><span className="dot" style={{ background: "var(--s8)" }} />{ao.haunted_nights} haunted {ao.haunted_nights === 1 ? "night" : "nights"}</span>}
            </div>
          </div>
          {b && (
            <div>
              <div className="muted" style={{ fontSize: 13, marginBottom: 4 }}>
                {b.always_on.percentile >= 50
                  ? `Higher than ${Math.round(b.always_on.percentile)}% of ${b.population.toLocaleString("en-GB")} London homes`
                  : `Lower than ${Math.round(100 - b.always_on.percentile)}% of ${b.population.toLocaleString("en-GB")} London homes`}
              </div>
              <Histogram edges={b.always_on.histogram.edges} counts={b.always_on.histogram.counts} value={ao.watts} median={b.always_on.median_w} />
              <div className="muted" style={{ fontSize: 11 }}>Low Carbon London smart meter trial, 2011–2014. A reference point, not a target.</div>
            </div>
          )}
        </section>
      ) : (
        <div className="notice warn"><div className="notice-title">Not enough data for the always-on estimate</div>{data.always_on_error}</div>
      )}

      <div className="grid kpis">
        <div className="card stat"><div className="label">Average day</div><div className="value">{kwh(s.avg_daily_kwh)}</div><div className="note">{s.complete_days} complete days</div></div>
        <div className="card stat"><div className="label">Per year</div><div className="value">{kwh(s.annualized_kwh, 0)}</div>{b?.annual && <div className="note">London median {kwh(b.annual.median_kwh, 0)}</div>}</div>
        <div className="card stat"><div className="label">Highest half hour</div><div className="value">{watts(s.peak_w)}</div><div className="note">{s.peak_at ? shortDate(s.peak_at) : ""}</div></div>
        <div className="card stat"><div className="label">Readings present</div><div className="value">{pct(s.coverage, 1)}</div><div className="note">{s.interval_minutes}-minute data, {shortDate(s.start)} – {shortDate(s.end)}</div></div>
      </div>

      <section className="card">
        <div className="card-head">
          <h2>Every half hour of the last year</h2>
          {/* Copy must not depend on light/dark: the ramp runs opposite ways in the two themes (low values darker on dark, lighter on light) */}
          <span className="sub">Faint cells at night mean small vampires. A strong band at 3 am means something never switches off.</span>
        </div>
        {heat ? <Heatmap data={heat} /> : <div className="empty loading">Summoning the heatmap…</div>}
      </section>
      <SourceNote data={data} />
    </div>
  );
}

function SourceNote({ data }: { data: OverviewData }) {
  const src = data.source;
  if (src.kind === "demo") {
    return (
      <p className="footer">
        Demo home: household {String(src.household)} from the Low Carbon London smart meter trial (UK Power Networks),
        published on the London Datastore under CC BY 4.0. Real readings, real gaps.
      </p>
    );
  }
  return (
    <p className="footer">
      Imported from {String(src.filename ?? "your file")} · read by {src.parsed_by === "ai" ? "the AI-checked settings" : "automatic detection"}
      {src.report ? ` · quality ${src.report.score}/100` : ""}
    </p>
  );
}

// Vampire hunt tab: daily floor, haunted nights list (click to see the day), suspect-device checklist.
import { useEffect, useMemo, useState } from "react";
import { DayChart } from "../charts/DayChart";
import { TableToggle } from "../charts/DataTable";
import { FloorChart } from "../charts/FloorChart";
import { api } from "../lib/api";
import { kwh, monthLabel, shortDate, watts, weekday } from "../lib/format";
import type { DayDetail, SuspectBreakdown, VampireReport } from "../lib/types";

export function Vampires({ id }: { id: string }) {
  const [rep, setRep] = useState<VampireReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [day, setDay] = useState<DayDetail | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const [owned, setOwned] = useState<Record<string, number>>({});
  const [breakdown, setBreakdown] = useState<SuspectBreakdown | null>(null);

  useEffect(() => {
    let live = true;
    setRep(null); setError(null); setDay(null); setPicked(null);
    api.vampires(id).then((r) => {
      if (!live) return;
      setRep(r);
      setBreakdown(r.suspects);
      setOwned(Object.fromEntries(r.suspects.items.map((i) => [i.id, i.quantity])));
      if (r.haunted_nights[0]) setPicked(r.haunted_nights[0].date);
    }).catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [id]);

  useEffect(() => {
    if (!picked) return;
    let live = true;
    api.day(id, picked).then((d) => live && setDay(d));
    return () => { live = false; };
  }, [id, picked]);

  const haunted = useMemo(() => new Set(rep?.haunted_nights.map((n) => n.date)), [rep]);

  function changeDevice(devId: string, delta: number) {
    const next = { ...owned, [devId]: Math.max(0, Math.min(20, (owned[devId] ?? 0) + delta)) };
    setOwned(next);
    api.setDevices(id, next).then(setBreakdown).catch(() => undefined);
  }

  if (error) return <div className="notice error">{error}</div>;
  if (!rep || !breakdown) return <div className="empty loading">Lighting candles…</div>;
  const maxExcess = Math.max(...rep.haunted_nights.map((n) => n.excess_w), 1);
  const worst = rep.haunted_nights[0];

  return (
    <div className="stack">
      <section className="card">
        <div className="card-head">
          <h2>The floor, day by day</h2>
          <span className="sub">Each point is the lowest power the home reached that day. Click a day to see it.</span>
        </div>
        <TableToggle
          columns={[{ label: "Month" }, { label: "Typical floor", num: true }]}
          rows={rep.monthly.map((mo) => [monthLabel(mo.month), watts(mo.floor_w)])}
        >
          <FloorChart data={rep.daily} haunted={haunted} alwaysOn={rep.watts} onPick={setPicked} />
        </TableToggle>
      </section>

      <div className="grid two">
        <section className="card">
          <div className="card-head">
            <h2>Haunted nights</h2>
            <span className="sub">{rep.haunted_nights.length ? `${rep.haunted_nights.length} days the floor rose well above normal` : "None found"}</span>
          </div>
          {rep.haunted_nights.length === 0 ? (
            <p className="secondary">The floor stayed close to its usual level all year. Whatever lives here keeps regular hours.</p>
          ) : (
            <>
              {worst && (
                <p className="secondary" style={{ marginBottom: 12 }}>
                  On {weekday(worst.date)} {shortDate(worst.date)} something drew an extra <strong>{watts(worst.excess_w)}</strong> all day and night,
                  at least {kwh(worst.extra_kwh)} more than usual.
                </p>
              )}
              <div className="nights" style={{ maxHeight: 360, overflowY: "auto" }}>
                {rep.haunted_nights.slice(0, 30).map((n) => (
                  <button key={n.date} className="night" aria-pressed={picked === n.date} onClick={() => setPicked(n.date)}>
                    <span className="date">{weekday(n.date)} {shortDate(n.date)}</span>
                    <span className="bar"><span style={{ width: `${(n.excess_w / maxExcess) * 100}%` }} /></span>
                    <span className="x">+{watts(n.excess_w)}</span>
                  </button>
                ))}
              </div>
            </>
          )}
        </section>
        <section className="card">
          <div className="card-head">
            <h2>{picked ? `${weekday(picked)} ${shortDate(picked)}` : "Pick a day"}</h2>
            {day?.found && <span className="sub">{kwh(day.kwh)} · lowest {watts(day.min_w)}</span>}
          </div>
          {day?.found && day.slots && day.watts ? (
            <TableToggle columns={[{ label: "Time" }, { label: "Power", num: true }]} rows={day.slots.map((s, i) => [s, watts(day.watts![i])])}>
              <DayChart slots={day.slots} values={day.watts} floor={rep.watts} />
            </TableToggle>
          ) : (
            <div className="empty">Choose a haunted night, or click any day on the chart above.</div>
          )}
        </section>
      </div>

      <section className="card">
        <div className="card-head">
          <h2>Who is in the walls?</h2>
          <span className="sub">Tick what you own. Watts are NRDC's measured averages per device.</span>
        </div>
        <Breakdown b={breakdown} />
        <div className="suspects" style={{ marginTop: 14 }}>
          {rep.catalogue.devices.map((d) => {
            const q = owned[d.id] ?? 0;
            return (
              <div key={d.id} className={`suspect${q ? " on" : ""}`}>
                <span className="nm">{d.name}</span>
                <span className="stepper" aria-label={`${d.name} count`}>
                  <button onClick={() => changeDevice(d.id, -1)} aria-label={`Remove ${d.name}`}>−</button>
                  <span>{q}</span>
                  <button onClick={() => changeDevice(d.id, 1)} aria-label={`Add ${d.name}`}>+</button>
                </span>
                <span className="wt">{d.watts} W each{d.estimate ? " (estimate)" : ""} · {d.kind === "resident" ? "needs to stay on" : "can be switched off"}</span>
                <span className="tip">{d.tip}</span>
              </div>
            );
          })}
        </div>
        <p className="footer" style={{ marginTop: 14 }}>
          Device watts: <a href={rep.catalogue.source_url} target="_blank" rel="noreferrer">NRDC, Home Idle Load (2015)</a>, Table 3.
          Fridge-freezer value is an estimate from typical energy labels.
        </p>
      </section>
    </div>
  );
}

function Breakdown({ b }: { b: SuspectBreakdown }) {
  const total = Math.max(b.always_on_w, b.explained_w, 1);
  const resident = b.explained_w - b.vampire_w;
  const parts = [
    { key: "vampire", label: "Vampires you can switch off", w: b.vampire_w, color: "var(--s1)" },
    { key: "resident", label: "Residents that stay on", w: resident, color: "var(--s2)" },
    { key: "unknown", label: "Not yet explained", w: b.unexplained_w, color: "var(--s7)" },
  ].filter((p) => p.w > 0);
  return (
    <div>
      <div className="segbar" role="img" aria-label={parts.map((p) => `${p.label} ${watts(p.w)}`).join(", ")}>
        {parts.map((p) => {
          const share = p.w / total;
          return (
            <div key={p.key} style={{ width: `${share * 100}%`, background: p.color }} title={`${p.label}: ${watts(p.w)}`}>
              {share > 0.12 ? watts(p.w) : ""}
            </div>
          );
        })}
      </div>
      <div className="legend">
        {parts.map((p) => <span key={p.key}><i className="swatch" style={{ background: p.color }} />{p.label}</span>)}
      </div>
      {b.explained_w > b.always_on_w && (
        <p className="muted" style={{ fontSize: 12, marginTop: 6 }}>
          The ticked devices add up to more than the measured floor, so some of them are probably more efficient than NRDC's average.
        </p>
      )}
    </div>
  );
}

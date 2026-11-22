// Import wizard: pick a file -> preview what was detected (raw lines, columns and unit, ambiguity notes) -> import.
// The user can change key settings in the preview (time column, reading column, unit, interval marking, zone); edited settings are sent as config.
import { useState } from "react";
import { api, ApiError } from "../lib/api";
import type { HouseholdCard, ImportPreview } from "../lib/types";

const ZONES = ["Europe/London", "Europe/Dublin", "Europe/Berlin", "Europe/Madrid", "Europe/Paris", "America/New_York", "America/Chicago",
  "America/Denver", "America/Los_Angeles", "Australia/Sydney", "Australia/Brisbane", "Asia/Tokyo", "Asia/Shanghai", "UTC"];

export function Importer({ onDone, onCancel }: { onDone: (h: HouseholdCard) => void; onCancel: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [tz, setTz] = useState(Intl.DateTimeFormat().resolvedOptions().timeZone || "Europe/London");
  const [name, setName] = useState("My home");
  const [prev, setPrev] = useState<ImportPreview | null>(null);
  const [cfg, setCfg] = useState<Record<string, unknown> | null>(null);
  const [edited, setEdited] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [over, setOver] = useState(false);

  async function pick(f: File) {
    setFile(f); setError(null); setPrev(null); setEdited(false); setBusy(true);
    try {
      const p = await api.preview(f, tz);
      setPrev(p); setCfg(p.config);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    if (!file) return;
    setBusy(true); setError(null);
    try {
      const res = await api.create(file, name, tz, edited && cfg ? { ...cfg, timezone: tz } : undefined);
      onDone(res.household);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const set = (k: string, v: unknown) => { setCfg((c) => ({ ...(c ?? {}), [k]: v })); setEdited(true); };
  const columns = prev?.columns ?? [];
  const isWide = cfg?.layout === "wide";
  const isXml = cfg?.file_kind === "greenbutton_xml";

  return (
    <div className="stack">
      <div className="row">
        <h1 style={{ fontSize: 26 }}>Bring your meter data</h1>
        <span className="spacer" />
        <button className="btn ghost" onClick={onCancel}>Back</button>
      </div>
      <p className="secondary" style={{ maxWidth: "70ch" }}>
        Download your half-hourly or hourly usage from your supplier, meter portal or "Green Button" page, and drop it here.
        CSV, Excel and Green Button XML all work. The file is read on this server and is not sent anywhere else;
        if the automatic reading is unsure, only the first 25 lines are shown to a Kiro Crew agent for a second opinion.
      </p>
      <div className="grid two">
        <label className="field">Name this home<input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} /></label>
        <label className="field">Time zone of the home
          <select value={tz} onChange={(e) => { setTz(e.target.value); if (file) void pick(file); }}>
            {[tz, ...ZONES.filter((z) => z !== tz)].map((z) => <option key={z}>{z}</option>)}
          </select>
        </label>
      </div>
      <label
        className={`dropzone${over ? " over" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files[0]; if (f) void pick(f); }}
      >
        <input type="file" accept=".csv,.txt,.xlsx,.xml" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) void pick(f); }} />
        <div style={{ fontSize: 16, fontWeight: 600 }}>{file ? file.name : "Drop a file, or click to choose one"}</div>
        <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>Up to 60 MB · a year or more of readings gives the best haunting statistics</div>
      </label>

      {busy && <div className="notice">Reading the file…</div>}
      {error && <div className="notice error"><div className="notice-title">That file could not be read</div>{error}</div>}

      {prev && cfg && (
        <section className="card stack">
          <div className="card-head"><h2>What we found</h2><span className="sub">Check these settings, then import.</span></div>
          {prev.notes.length > 0 && <ul style={{ margin: 0, paddingLeft: 18 }} className="secondary">{prev.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
          {prev.ambiguities.length > 0 && (
            <div className="notice warn">
              <div className="notice-title">Worth a look</div>
              {prev.ambiguities.map((a) => <div key={a}>{a}</div>)}
              <div className="muted" style={{ marginTop: 4 }}>If you import without changes, the Kiro Crew agent will review these settings when it is available.</div>
            </div>
          )}
          <div className="preview-lines">{prev.preview.slice(0, 14).join("\n")}</div>
          {!isXml && (
            <div className="grid three">
              {!isWide && cfg.time_column == null && (
                <label className="field">Timestamp column
                  <select value={String(cfg.timestamp_column ?? "")} onChange={(e) => set("timestamp_column", e.target.value || null)}>
                    <option value="">—</option>{columns.map((c) => <option key={c}>{c}</option>)}
                  </select>
                </label>
              )}
              {!isWide && (
                <label className="field">Reading column
                  <select value={String(cfg.value_column ?? "")} onChange={(e) => set("value_column", e.target.value || null)}>
                    <option value="">—</option>{columns.map((c) => <option key={c}>{c}</option>)}
                  </select>
                </label>
              )}
              <label className="field">Unit
                <select value={String(cfg.unit)} onChange={(e) => set("unit", e.target.value)}>
                  {["kWh", "Wh", "MWh", "kW", "W"].map((u) => <option key={u}>{u}</option>)}
                </select>
              </label>
              {!isWide && (
                <label className="field">Timestamps mark
                  <select value={String(cfg.timestamp_marks)} onChange={(e) => set("timestamp_marks", e.target.value)}>
                    <option value="start">the start of each interval</option>
                    <option value="end">the end of each interval</option>
                  </select>
                </label>
              )}
              <label className="field">Readings are
                <select value={String(cfg.reading_type)} onChange={(e) => set("reading_type", e.target.value)}>
                  <option value="interval">energy or power per interval</option>
                  <option value="cumulative">meter register totals</option>
                </select>
              </label>
              {prev.meter_ids.length > 1 && (
                <label className="field">Meter
                  <select value={String(cfg.meter_id ?? "")} onChange={(e) => set("meter_id", e.target.value)}>
                    {prev.meter_ids.map((m) => <option key={m}>{m}</option>)}
                  </select>
                </label>
              )}
            </div>
          )}
          <div className="row">
            <button className="btn primary" onClick={submit} disabled={busy}>Import and analyse</button>
            {edited && <span className="muted" style={{ fontSize: 13 }}>Your settings will be used as shown.</span>}
          </div>
        </section>
      )}
    </div>
  );
}

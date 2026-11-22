// Tariff tab: annual bills ranked cheapest first, the load-shift slider, and tariff prices against the average day.
import { useEffect, useState } from "react";
import { TableToggle } from "../charts/DataTable";
import { PriceProfile } from "../charts/PriceProfile";
import { api } from "../lib/api";
import { kwh, money, shortDate } from "../lib/format";
import type { BillsResponse } from "../lib/types";

// Tariff colours follow the tariff itself (fixed by id), so moving the slider never recolours anything
const COLORS: Record<string, string> = {
  "octopus-flexible": "var(--s1)", "octopus-go": "var(--s2)", "octopus-cosy": "var(--s3)", "octopus-agile": "var(--s7)",
};

export function Tariffs({ id }: { id: string }) {
  const [shift, setShift] = useState(2);
  const [data, setData] = useState<BillsResponse | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let live = true;
    setLoading(true);
    const t = setTimeout(() => {
      api.bills(id, shift).then((d) => live && setData(d)).finally(() => live && setLoading(false));
    }, 150);
    return () => { live = false; clearTimeout(t); };
  }, [id, shift]);

  if (!data) return <div className="empty loading">Reading the tea leaves…</div>;
  const bills = data.bills;
  const max = Math.max(...bills.map((b) => b.annual_cost));
  const cur = bills[0]?.currency ?? "GBP";
  const best = bills[0];
  const flat = bills.find((b) => b.kind === "flat");
  const bestShift = bills.filter((b) => b.shift).sort((a, b) => (b.shift!.annual_saving - a.shift!.annual_saving))[0];

  return (
    <div className={`stack${loading ? " loading" : ""}`}>
      <section className="card">
        <div className="card-head">
          <h2>Your last 12 months on each tariff</h2>
          <span className="sub">Same half-hourly usage, real London prices from Octopus Energy ({data.snapshot.fetched_at ? shortDate(data.snapshot.fetched_at) : "snapshot"})</span>
        </div>
        {best && flat && best.tariff_id !== flat.tariff_id && (
          <p className="secondary" style={{ marginBottom: 14 }}>
            <strong>{best.tariff_name}</strong> would have cost {money(flat.annual_cost - best.annual_cost, cur)} less than the single-rate tariff,
            without changing a single habit.
          </p>
        )}
        <TableToggle
          columns={[{ label: "Tariff" }, { label: "Year", num: true }, { label: "Energy", num: true }, { label: "Standing", num: true }, { label: "Average per kWh", num: true }]}
          rows={bills.map((b) => [b.tariff_name, money(b.annual_cost, cur), money(b.energy_cost, cur), money(b.standing_cost, cur), money(b.average_price, cur)])}
        >
          <div className="bill-list">
            {bills.map((b, i) => (
              <div key={b.tariff_id} className={`bill${i === 0 ? " best" : ""}`}>
                <div>
                  <div className="t-name"><i className="key" style={{ display: "inline-block", width: 14, height: 2, background: COLORS[b.tariff_id] ?? "var(--s4)", verticalAlign: "middle", marginRight: 8 }} />{b.tariff_name}</div>
                  <div className="t-note">{b.notes}</div>
                </div>
                {/* The bill bar uses the tariff's colour from the price chart: colour follows the tariff, not its rank */}
                <div className="track" aria-hidden="true"><span style={{ width: `${(b.annual_cost / max) * 100}%`, background: COLORS[b.tariff_id] ?? "var(--s4)" }} /></div>
                <div>
                  <div className="t-cost">{money(b.annual_cost, cur)}</div>
                  <div className="t-delta">{i === 0 ? "cheapest" : `+${money(b.vs_cheapest, cur)}`} · {money(b.average_price, cur)}/kWh</div>
                </div>
              </div>
            ))}
          </div>
        </TableToggle>
        <p className="footer" style={{ marginTop: 12 }}>
          Bills use the most recent {Math.round(bills[0]?.days ?? 365)} days, annualised, with standing charges. Missing readings are filled from the same time on similar days.
          Agile uses the average price for each half hour, month and day type over the past year.
        </p>
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Move the dishwasher to the cheap hours</h2>
          <span className="sub">An estimate on your average day. The always-on floor cannot be moved.</span>
        </div>
        <div className="row wrap" style={{ gap: 18 }}>
          <label className="field" style={{ flexDirection: "row", alignItems: "center", gap: 12 }}>
            Shift
            <input type="range" min={0} max={8} step={0.5} value={shift} onChange={(e) => setShift(Number(e.target.value))} aria-label="kWh per day to shift" />
            <strong className="num">{kwh(shift)} a day</strong>
          </label>
          {bestShift?.shift && (
            <span className="secondary">
              On <strong>{bestShift.tariff_name}</strong> that saves about <strong>{money(bestShift.shift.annual_saving, cur)}</strong> a year
              {bestShift.shift.shiftable_kwh_per_day < shift - 0.01 ? ` (only ${kwh(bestShift.shift.shiftable_kwh_per_day)} a day is flexible)` : ""}.
            </span>
          )}
        </div>
        <div className="grid three" style={{ marginTop: 14 }}>
          {bills.filter((b) => b.shift).map((b) => (
            <div key={b.tariff_id} className="card stat" style={{ background: "var(--card-raised)" }}>
              <div className="label">{b.tariff_name}</div>
              <div className="value">{money(b.shift!.annual_saving, cur)}</div>
              <div className="note">a year, moving load to {b.shift!.cheapest_slot}</div>
            </div>
          ))}
        </div>
      </section>

      <section className="card">
        <div className="card-head">
          <h2>When electricity is cheap, and when you use it</h2>
          <span className="sub">Prices on top, your average power below, same clock</span>
        </div>
        <PriceProfile
          currency={cur}
          slots={Array.from({ length: 48 }, (_, i) => `${String(Math.floor(i / 2)).padStart(2, "0")}:${i % 2 ? "30" : "00"}`)}
          weekday={data.usage_profile.weekday_w}
          weekend={data.usage_profile.weekend_w}
          series={bills.filter((b) => b.kind !== "flat" || b.tariff_id === "octopus-flexible").map((b) => ({
            id: b.tariff_id, name: b.tariff_name.split(" (")[0], color: COLORS[b.tariff_id] ?? "var(--s4)", prices: b.slot_prices,
          }))}
        />
      </section>
    </div>
  );
}

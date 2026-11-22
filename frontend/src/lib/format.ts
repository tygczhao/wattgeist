// Number formatting, matching steering/frontend-design.md (W without decimals, kWh with one decimal, money with two).

const SYMBOL: Record<string, string> = { GBP: "£", USD: "$", EUR: "€", AUD: "A$" };

export function watts(w: number | null | undefined): string {
  if (w == null || Number.isNaN(w)) return "–";
  if (Math.abs(w) >= 1000) return `${(w / 1000).toFixed(w >= 10000 ? 0 : 1)} kW`;
  return `${Math.abs(w) >= 10 ? Math.round(w) : w.toFixed(1)} W`;
}

export function kwh(v: number | null | undefined, digits = 1): string {
  if (v == null || Number.isNaN(v)) return "–";
  return `${v.toLocaleString("en-GB", { maximumFractionDigits: digits, minimumFractionDigits: v >= 1000 ? 0 : digits })} kWh`;
}

export function money(v: number | null | undefined, currency = "GBP"): string {
  if (v == null || Number.isNaN(v)) return "–";
  const sym = SYMBOL[currency] ?? `${currency} `;
  const sign = v < 0 ? "−" : "";
  return `${sign}${sym}${Math.abs(v).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function pct(v: number | null | undefined, digits = 0): string {
  if (v == null || Number.isNaN(v)) return "–";
  return `${(v * 100).toFixed(digits)}%`;
}

/** English ordinal suffix: 11–13 take "th", otherwise the last digit 1/2/3 takes st/nd/rd. */
export function ordinal(n: number): string {
  const r = Math.round(n);
  const teen = r % 100 >= 11 && r % 100 <= 13;
  const suffix = teen ? "th" : ({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[r % 10] ?? "th";
  return `${r}${suffix}`;
}

export function shortDate(iso: string): string {
  const d = new Date(iso.length === 10 ? `${iso}T12:00:00Z` : iso);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

export function weekday(iso: string): string {
  return new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-GB", { weekday: "short", timeZone: "UTC" });
}

export function monthLabel(ym: string): string {
  const [y, m] = ym.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, 15)).toLocaleDateString("en-GB", { month: "short", year: "2-digit", timeZone: "UTC" });
}

/** Axis ticks: a clean 1/2/5 x 10^k step, starting at 0 and covering max. */
export function niceTicks(max: number, count = 4): number[] {
  if (!(max > 0)) return [0, 1];
  const raw = max / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? 10 * mag;
  const ticks: number[] = [];
  for (let v = 0; v <= max + step * 0.001; v += step) ticks.push(Number(v.toPrecision(12)));
  if (ticks[ticks.length - 1] < max) ticks.push(Number((ticks[ticks.length - 1] + step).toPrecision(12)));
  return ticks;
}

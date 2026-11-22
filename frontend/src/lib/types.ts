// Types mirroring the shapes returned by the backend's service.py. Field names keep the backend's snake_case so the two sides never drift.

export interface HouseholdCard {
  id: string;
  name: string;
  demo: boolean;
  tagline: string;
  timezone: string;
  always_on_w?: number;
  annual_kwh?: number;
  share?: number;
  error?: string;
}

export interface Benchmark {
  population: number;
  source: string;
  always_on: { percentile: number; median_w: number; p25_w: number; p75_w: number; histogram: { edges: number[]; counts: number[] } };
  annual?: { percentile: number; median_kwh: number };
}

export interface Overview {
  household: HouseholdCard;
  summary: {
    start: string; end: string; days: number; complete_days: number; coverage: number;
    interval_minutes: number; timezone: string; total_kwh: number; avg_daily_kwh: number | null;
    annualized_kwh: number | null; peak_w: number | null; peak_at: string | null;
  };
  source: Record<string, unknown> & { kind?: string; notes?: string[]; ai_notes?: string[]; parsed_by?: string; dataset?: string; household?: string; report?: ParseReport; filename?: string };
  always_on: null | {
    watts: number; annual_kwh: number; share: number; annual_cost: number | null; price_used: number | null;
    currency: string | null; days_used: number; days_excluded: number; haunted_nights: number;
  };
  always_on_error?: string;
  benchmark: Benchmark | null;
}

export interface ParseReport {
  rows_total: number; rows_used: number; timestamp_failures: number; value_failures: number;
  duplicate_timestamps: number; negative_values: number; cumulative_resets: number;
  native_interval_minutes: number; interval_minutes: number; regularity: number; coverage: number;
  start: string; end: string; days: number; median_power_w: number; warnings: string[]; score: number;
}

export interface Device {
  id: string; name: string; watts: number; kind: "vampire" | "resident"; tip: string; estimate?: boolean;
}

export interface SuspectBreakdown {
  always_on_w: number; explained_w: number; vampire_w: number; unexplained_w: number;
  items: (Device & { quantity: number; total_w: number })[];
}

export interface HauntedNight { date: string; floor_w: number; excess_w: number; extra_kwh: number }

export interface VampireReport {
  watts: number; annual_kwh: number; share: number;
  daily: { date: string; floor_w: number; baseline_w: number }[];
  monthly: { month: string; floor_w: number }[];
  haunted_nights: HauntedNight[];
  suspects: SuspectBreakdown;
  catalogue: { source: string; source_url: string; devices: Device[] };
}

export interface Heatmap { dates: string[]; slots: string[]; watts: (number | null)[][] }

export interface Bill {
  tariff_id: string; tariff_name: string; currency: string; annual_cost: number; energy_cost: number;
  standing_cost: number; annual_kwh: number; average_price: number; days: number; filled_share: number;
  kind: "flat" | "tou" | "dynamic"; notes: string; slot_prices: number[]; vs_cheapest: number;
  shift: null | { annual_saving: number; shiftable_kwh_per_day: number; cheapest_slot: string; requested_kwh_per_day: number };
}

export interface BillsResponse {
  bills: Bill[];
  usage_profile: { slots: string[]; weekday_w: (number | null)[]; weekend_w: (number | null)[] };
  snapshot: { fetched_at: string | null; source: string | null; region: string | null };
  kwh_to_shift: number;
}

export interface DayDetail { date: string; found: boolean; kwh?: number; min_w?: number; max_w?: number; slots?: string[]; watts?: (number | null)[] }

export interface ParseConfig { [key: string]: unknown }

export interface ImportPreview {
  preview: string[]; columns: string[]; config: ParseConfig; notes: string[]; ambiguities: string[]; meter_ids: string[];
}

export type AskEvent =
  | { type: "text"; delta: string }
  | { type: "done" }
  | { type: "error"; message: string };

// Backend API client. Every request goes to same-origin /api; in development Vite proxies it.
import type { AskEvent, BillsResponse, DayDetail, Heatmap, HouseholdCard, ImportPreview, Overview, SuspectBreakdown, VampireReport } from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* Non-JSON error body: keep the status text */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

const get = <T,>(path: string) => fetch(path).then((r) => json<T>(r));

export const api = {
  health: () => get<{ ok: boolean; ai: boolean; version: string }>("/api/health"),
  households: () => get<HouseholdCard[]>("/api/households"),
  overview: (id: string) => get<Overview>(`/api/households/${encodeURIComponent(id)}/overview`),
  vampires: (id: string) => get<VampireReport>(`/api/households/${encodeURIComponent(id)}/vampires`),
  heatmap: (id: string, days = 365) => get<Heatmap>(`/api/households/${encodeURIComponent(id)}/heatmap?days=${days}`),
  bills: (id: string, shift = 2) => get<BillsResponse>(`/api/households/${encodeURIComponent(id)}/bills?shift_kwh=${shift}`),
  day: (id: string, date: string) => get<DayDetail>(`/api/households/${encodeURIComponent(id)}/day/${date}`),
  setDevices: (id: string, devices: Record<string, number>) =>
    fetch(`/api/households/${encodeURIComponent(id)}/devices`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ devices }),
    }).then((r) => json<SuspectBreakdown>(r)),
  preview: (file: File, timezone: string) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("timezone", timezone);
    return fetch("/api/import/preview", { method: "POST", body: fd }).then((r) => json<ImportPreview>(r));
  },
  create: (file: File, name: string, timezone: string, config?: Record<string, unknown>) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("name", name);
    fd.append("timezone", timezone);
    if (config) fd.append("config", JSON.stringify(config));
    return fetch("/api/households", { method: "POST", body: fd }).then((r) =>
      json<{ household: HouseholdCard; source: Overview["source"] }>(r));
  },
  remove: (id: string) => fetch(`/api/households/${encodeURIComponent(id)}`, { method: "DELETE" }).then((r) => json(r)),
};

/** Streamed Q&A: parse NDJSON line by line and call back once per event. Returns a function that aborts the request. */
export function ask(
  id: string,
  question: string,
  history: { role: "user" | "assistant"; content: string }[],
  onEvent: (e: AskEvent) => void,
): () => void {
  const ctrl = new AbortController();
  (async () => {
    try {
      const res = await fetch(`/api/households/${encodeURIComponent(id)}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, history }),
        signal: ctrl.signal,
      });
      if (!res.ok || !res.body) {
        const err = await json<never>(res).catch((e: ApiError) => e);
        onEvent({ type: "error", message: err instanceof Error ? err.message : "Request failed" });
        return;
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let nl: number;
        while ((nl = buf.indexOf("\n")) >= 0) {
          const line = buf.slice(0, nl).trim();
          buf = buf.slice(nl + 1);
          if (line) onEvent(JSON.parse(line) as AskEvent);
        }
      }
      if (buf.trim()) onEvent(JSON.parse(buf) as AskEvent);
    } catch (e) {
      if ((e as Error).name !== "AbortError") onEvent({ type: "error", message: (e as Error).message });
    }
  })();
  return () => ctrl.abort();
}

// App shell: household list on the left (demo homes + imported ones), four tabs on the right. The theme lives on <html data-theme>.
import { useCallback, useEffect, useState } from "react";
import { Importer } from "./components/Importer";
import { Overview } from "./components/Overview";
import { Seance } from "./components/Seance";
import { Tariffs } from "./components/Tariffs";
import { Vampires } from "./components/Vampires";
import { api } from "./lib/api";
import { watts } from "./lib/format";
import type { HouseholdCard, Overview as OverviewData } from "./lib/types";

type Tab = "overview" | "vampires" | "tariffs" | "seance";
const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "vampires", label: "Vampire hunt" },
  { id: "tariffs", label: "Tariffs" },
  { id: "seance", label: "Séance" },
];

function readHash(): { id: string | null; tab: Tab } {
  const [id, tab] = window.location.hash.replace(/^#\/?/, "").split("/");
  return { id: id || null, tab: (TABS.some((t) => t.id === tab) ? tab : "overview") as Tab };
}

export function App() {
  const [homes, setHomes] = useState<HouseholdCard[]>([]);
  const [{ id, tab }, setRoute] = useState(readHash);
  const [overview, setOverview] = useState<OverviewData | null>(null);
  const [importing, setImporting] = useState(false);
  const [ai, setAi] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [theme, setTheme] = useState<"dark" | "light">(() => (localStorage.getItem("wg-theme") as "light") || "dark");

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("wg-theme", theme);
  }, [theme]);

  const go = useCallback((nextId: string | null, nextTab: Tab = "overview") => {
    window.location.hash = nextId ? `/${nextId}/${nextTab}` : "";
    setRoute({ id: nextId, tab: nextTab });
  }, []);

  const loadHomes = useCallback(async () => {
    const list = await api.households();
    setHomes(list);
    return list;
  }, []);

  useEffect(() => {
    api.health().then((h) => setAi(h.ai)).catch(() => setAi(false));
    loadHomes().then((list) => {
      if (!readHash().id && list.length) go(list.find((h) => h.id === "haunted-semi")?.id ?? list[0].id);
    }).catch((e) => setError(String(e.message ?? e)));
    const onHash = () => setRoute(readHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [go, loadHomes]);

  useEffect(() => {
    if (!id) return;
    let live = true;
    api.overview(id).then((o) => live && setOverview(o)).catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [id]);

  const current = homes.find((h) => h.id === id);
  const demos = homes.filter((h) => h.demo);
  const mine = homes.filter((h) => !h.demo);

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <svg width="34" height="34" viewBox="0 0 64 64" aria-hidden="true">
            <path d="M32 6c-12 0-20 9-20 21v27l6-5 5 5 5-5 4 5 4-5 5 5 5-5 6 5V27C52 15 44 6 32 6z" fill="var(--text)" />
            <circle cx="24" cy="28" r="4" fill="var(--page)" /><circle cx="40" cy="28" r="4" fill="var(--page)" />
            <path d="M34 34l-6 9h5l-3 8 9-11h-5l3-6z" fill="var(--accent)" />
          </svg>
          <div>
            <div className="brand-name">WattGeist</div>
            <div className="brand-sub">The home energy monitor, back from the dead</div>
          </div>
        </div>
        <button className="btn primary" onClick={() => setImporting(true)}>Import my meter data</button>
        {mine.length > 0 && (
          <div>
            <div className="section-label">Your homes</div>
            <HomeList homes={mine} current={id} onPick={(h) => { setImporting(false); go(h, tab); }} />
          </div>
        )}
        <div>
          <div className="section-label">Haunted London homes</div>
          <HomeList homes={demos} current={id} onPick={(h) => { setImporting(false); go(h, tab); }} />
        </div>
        <div className="spacer" />
        <div className="row" style={{ justifyContent: "space-between" }}>
          <button className="btn ghost small" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
            {theme === "dark" ? "Lights on" : "Lights off"}
          </button>
          <span className="badge" title={ai ? "AI answers and import review are on" : "AI is off on this server"}>
            <span className="dot" style={{ background: ai ? "var(--good)" : "var(--muted)" }} />AI {ai ? "on" : "off"}
          </span>
        </div>
      </aside>

      <main className="main">
        {error && <div className="notice error" style={{ marginBottom: 16 }}>{error}</div>}
        {importing ? (
          <Importer
            onCancel={() => setImporting(false)}
            onDone={async (h) => { await loadHomes(); setImporting(false); go(h.id, "overview"); }}
          />
        ) : current && overview && overview.household.id === id ? (
          <>
            <header className="row" style={{ alignItems: "flex-end" }}>
              <div>
                <h1 style={{ fontSize: 28 }}>{current.name}</h1>
                <p className="muted">{current.tagline || `${current.timezone} · imported meter data`}</p>
              </div>
              <span className="spacer" />
              {!current.demo && (
                <button className="btn ghost small" onClick={async () => {
                  if (!confirm(`Delete ${current.name}? This removes its readings from this server.`)) return;
                  await api.remove(current.id); const list = await loadHomes(); go(list[0]?.id ?? null);
                }}>Delete</button>
              )}
            </header>
            <nav className="tabs" role="tablist">
              {TABS.map((t) => (
                <button key={t.id} role="tab" className="tab" aria-selected={tab === t.id} onClick={() => go(current.id, t.id)}>{t.label}</button>
              ))}
            </nav>
            {tab === "overview" && <Overview data={overview} onHunt={() => go(current.id, "vampires")} />}
            {tab === "vampires" && <Vampires id={current.id} />}
            {tab === "tariffs" && <Tariffs id={current.id} />}
            {tab === "seance" && <Seance id={current.id} ai={ai} name={current.name} />}
          </>
        ) : (
          <div className="empty loading">Opening the crypt…</div>
        )}
        <footer className="footer">
          WattGeist revives the idea of Google PowerMeter (2009–2011) and Microsoft Hohm (2009–2012) using the file your meter already gives you.
          Demo homes: Low Carbon London, UK Power Networks, CC BY 4.0. Standby watts: NRDC (2015). Tariffs: Octopus Energy public API.
        </footer>
      </main>
    </div>
  );
}

function HomeList({ homes, current, onPick }: { homes: HouseholdCard[]; current: string | null; onPick: (id: string) => void }) {
  return (
    <div className="home-list">
      {homes.map((h) => (
        <button key={h.id} className="home-item" aria-current={h.id === current} onClick={() => onPick(h.id)}>
          <span className="name">{h.name}</span>
          <span className="w">{h.always_on_w != null ? watts(h.always_on_w) : ""}</span>
          {h.tagline && <span className="tag">{h.tagline}</span>}
        </button>
      ))}
    </div>
  );
}

"""Build the demo households and the London benchmark from the raw Low Carbon London archive.

Usage (the downloaded archive is external data, so run isolated):
    uv run --project backend python -I scripts/build_demo_data.py <partitioned_lcl.zip> <output dir>

Steps:
1. Read the 168 partitions in parallel. The data is sorted by household and then split, so a household can span two neighbouring partitions;
   each partition's first and last household rows go back to the main process and are analysed once joined.
2. Each household is analysed with the app's own parser and estimator (exactly the production definitions): always-on load, annual use, night share, haunted nights.
3. Write benchmark.json (quantiles + histogram) and a few demo households as raw-format gzip CSV;
   in the app the demo households go through the full import pipeline, which also demonstrates Low Carbon London detection.
Data licence: CC BY 4.0, © UK Power Networks, via the London Datastore.
"""

from __future__ import annotations

import gzip
import io
import json
import sys
import zipfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from wattgeist.analysis.always_on import InsufficientData, estimate_always_on
from wattgeist.ingest.config import ParseConfig
from wattgeist.ingest.numbers import to_numbers
from wattgeist.ingest.parse import _normalize
from wattgeist.ingest.validate import ParseReport
from wattgeist.series import MeterSeries

HEADER = "LCLid,stdorToU,DateTime,KWH/hh (per half hour) "
LCL_CFG = ParseConfig(
    file_kind="csv", timestamp_column="DateTime", value_column="KWH/hh (per half hour)",
    unit="kWh", timestamp_marks="end", timezone="UTC", interval_minutes=30,
)
TZ = "Europe/London"


def _read_member(zip_path: str, member: str) -> pd.DataFrame:
    with zipfile.ZipFile(zip_path) as zf, zf.open(member) as fh:
        df = pd.read_csv(fh, dtype=str, keep_default_na=False)
    df.columns = ["LCLid", "stdorToU", "DateTime", "kwh"]
    return df


def household_metrics(df: pd.DataFrame) -> dict | None:
    """Metrics for one household; None when the data is not good enough (under 300 valid days in its last year), so it stays out of the distribution."""
    ts = pd.to_datetime(df["DateTime"].str[:19], format="%Y-%m-%d %H:%M:%S", errors="coerce").dt.tz_localize("UTC")
    values = to_numbers(df["kwh"])
    try:
        grid = _normalize(ts, values, LCL_CFG, ParseReport(), shift_end_marks=True, native_interval=30, cumulative=False)
    except Exception:  # noqa: BLE001  a household with broken data (all empty, all zero) is skipped without stopping the 5,000-home batch
        return None
    series = MeterSeries(energy_kwh=grid, interval_minutes=30, timezone=TZ)
    if (series.end - series.start).days < 365:
        return None
    try:
        ao = estimate_always_on(series)
    except InsufficientData:
        return None
    if ao.days_used < 300 or ao.annual_consumption_kwh <= 0:
        return None
    recent = series.last_days(365).local_energy()
    night = recent[(recent.index.hour < 7)].sum()
    return {
        "lclid": df["LCLid"].iloc[0],
        "tariff": df["stdorToU"].iloc[0],
        "always_on_w": ao.watts,
        "annual_kwh": ao.annual_consumption_kwh,
        "share": ao.share_of_consumption,
        "haunted": len(ao.haunted_nights),
        "night_share": float(night / recent.sum()) if recent.sum() > 0 else 0.0,
        "days": int((series.end - series.start).days),
        "coverage": series.coverage(),
    }


def process_partition(args: tuple[str, str]) -> tuple[list[dict], dict[str, pd.DataFrame], list[str]]:
    zip_path, member = args
    df = _read_member(zip_path, member)
    ids = df["LCLid"].unique().tolist()
    edge_ids = {ids[0], ids[-1]}
    metrics, edges = [], {}
    for lclid, g in df.groupby("LCLid", sort=False):
        if lclid in edge_ids:
            edges[lclid] = g
            continue
        m = household_metrics(g)
        if m:
            metrics.append(m)
    return metrics, edges, ids


def quantiles(values: np.ndarray) -> list[float]:
    return [round(float(v), 2) for v in np.percentile(values, np.arange(0, 101))]


def main(zip_path: str, out_dir: str, limit: int | None = None) -> None:
    out = Path(out_dir)
    (out / "demo").mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        members = sorted(n for n in zf.namelist() if n.endswith(".csv"))[:limit]
    metrics: list[dict] = []
    edges: dict[str, list[pd.DataFrame]] = {}
    located: dict[str, list[str]] = {}  # household id -> partitions containing it, so only those are re-read for the demo homes
    # Each worker holds one ~50 MB partition (several hundred MB in memory), so concurrency is limited by RAM
    with ProcessPoolExecutor(max_workers=4) as pool:
        tasks = [(zip_path, n) for n in members]
        for i, (m, e, ids) in enumerate(pool.map(process_partition, tasks)):
            metrics.extend(m)
            for k, v in e.items():
                edges.setdefault(k, []).append(v)
            for lclid in ids:
                located.setdefault(lclid, []).append(tasks[i][1])
            print(f"partition {i + 1}/{len(members)}: {len(metrics)} households", flush=True)
    for parts in edges.values():
        m = household_metrics(pd.concat(parts, ignore_index=True))
        if m:
            metrics.append(m)
    table = pd.DataFrame(metrics).drop_duplicates("lclid")
    table.to_csv(out / "household_metrics.csv.gz", index=False, compression="gzip")
    print("households in benchmark:", len(table))

    ao = table["always_on_w"].to_numpy()
    edges_w = list(range(0, 620, 20))
    counts, _ = np.histogram(np.clip(ao, 0, 619), bins=edges_w)
    bench = {
        "source": "Low Carbon London smart meter trial (UK Power Networks, 2011-2014), via London Datastore, CC BY 4.0",
        "households": int(len(table)),
        "always_on_w": {"quantiles": quantiles(ao), "histogram": {"edges": edges_w, "counts": counts.tolist()}},
        "annual_kwh": {"quantiles": quantiles(table["annual_kwh"].to_numpy())},
        "share": {"quantiles": quantiles(table["share"].to_numpy())},
    }
    (out / "benchmark.json").write_text(json.dumps(bench, indent=1))

    picks = choose_demo_households(table)
    index = []
    wanted = {p["lclid"] for p in picks}
    rows: dict[str, list[pd.DataFrame]] = {k: [] for k in wanted}
    for name in sorted({m for k in wanted for m in located[k]}):
        df = _read_member(zip_path, name)
        for lclid in wanted & set(df["LCLid"].unique()):
            rows[lclid].append(df[df["LCLid"] == lclid])
    for p in picks:
        g = pd.concat(rows[p["lclid"]], ignore_index=True)
        buf = io.StringIO()
        buf.write(HEADER + "\n")
        for r in g.itertuples(index=False):
            buf.write(f"{r.LCLid},{r.stdorToU},{r.DateTime},{r.kwh}\n")
        with gzip.open(out / "demo" / f"{p['id']}.csv.gz", "wt", encoding="utf-8") as fh:
            fh.write(buf.getvalue())
        index.append(p)
        print("demo", p["id"], p["lclid"], round(p["always_on_w"]), "W", round(p["annual_kwh"]), "kWh")
    (out / "demo" / "index.json").write_text(json.dumps(index, indent=1))


def choose_demo_households(t: pd.DataFrame) -> list[dict]:
    """Choose demo households by persona. Only standard-tariff homes with complete data are used, to avoid the behaviour of the 2013 dynamic-price trial group.

    Ranks are computed once over the full candidate set and stored as columns; each persona filters on those columns and already-chosen homes are excluded through used,
    so the percentile definitions in the filters are the same for every persona and do not drift as homes are taken.
    """
    good = t[(t["tariff"] == "Std") & (t["coverage"] > 0.97) & (t["days"] >= 500)].copy()
    good["ao_rank"] = good["always_on_w"].rank(pct=True)
    good["kwh_rank"] = good["annual_kwh"].rank(pct=True)
    used: set[str] = set()
    picks: list[dict] = []

    def pool(mask: pd.Series) -> pd.DataFrame:
        return good[mask & ~good["lclid"].isin(used)]

    def take(row: pd.Series, pid: str, name: str, tagline: str) -> None:
        d = {k: (v.item() if hasattr(v, "item") else v) for k, v in row.items()}
        d.update(id=pid, name=name, tagline=tagline)
        picks.append(d)
        used.add(row["lclid"])

    manor = pool((good["ao_rank"] > 0.95) & (good["ao_rank"] < 0.99) & (good["share"] > 0.4))
    take(manor.sort_values("always_on_w").iloc[-1], "vampire-manor", "The Vampire Manor",
         "Something in this house never sleeps.")
    typical = pool(good["lclid"].notna())
    typical = typical.assign(d=(typical["ao_rank"] - 0.5).abs() + (typical["kwh_rank"] - 0.5).abs())
    take(typical.sort_values("d").iloc[0], "ordinary-terrace", "The Ordinary Terrace",
         "A perfectly normal London home. Or is it?")
    frugal = pool((good["kwh_rank"] < 0.12) & (good["ao_rank"] < 0.25)).sort_values("annual_kwh")
    take(frugal.iloc[len(frugal) // 2], "frugal-flat", "The Frugal Flat", "Barely a whisper on the meter.")
    haunted = pool((good["ao_rank"] > 0.35) & (good["ao_rank"] < 0.75)).sort_values("haunted")
    take(haunted.iloc[-1], "haunted-semi", "The Haunted Semi", "Some nights, the floor rises and nobody knows why.")
    owl = pool(good["kwh_rank"] > 0.5).sort_values("night_share")
    take(owl.iloc[-1], "night-owl", "The Night Owl", "Most of its power is drawn while London sleeps.")
    return picks


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else None)

"""Fetch London (region C) household tariffs from the Octopus Energy public API and write the bundled tariff snapshot.

Usage: uv run --project backend python -I scripts/fetch_octopus_tariffs.py <output json path>

- Prices are what customers pay including VAT (value_inc_vat), converted from pence to pounds.
- Flat and time-of-use tariffs use the latest live prices; time-of-use windows are rebuilt from the most recent full local day of prices.
- Agile (dynamic) fetches the last 365 days of half-hourly prices and averages them by (month, weekday/weekend, half-hour slot)
  into a 12x2x48 typical price matrix that the bill engine uses (see tariffs/engine.py).
API docs: https://developer.octopus.energy/rest/
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta

import httpx
import numpy as np
import pandas as pd

BASE = "https://api.octopus.energy/v1/products"
REGION = "C"
TZ = "Europe/London"


def fetch_all(client: httpx.Client, url: str, params: dict | None = None) -> list[dict]:
    out, next_url, p = [], url, dict(params or {}, page_size=1500)
    while next_url:
        r = client.get(next_url, params=p, timeout=30)
        r.raise_for_status()
        data = r.json()
        out.extend(data["results"])
        next_url, p = data.get("next"), None
    return out


def latest(records: list[dict], payment: str = "DIRECT_DEBIT") -> float:
    """The price live now (valid_to empty or in the future); where payment methods differ, the direct-debit price."""
    now = datetime.now(UTC).isoformat()
    live = [r for r in records if (r["valid_to"] is None or r["valid_to"] > now) and r["valid_from"] <= now]
    live = [r for r in live if r.get("payment_method") in (payment, None)] or live
    return round(live[0]["value_inc_vat"] / 100.0, 5)


def tariff_code(product: str) -> str:
    return f"E-1R-{product}-{REGION}"


def derive_windows(records: list[dict]) -> tuple[float, list[dict]]:
    """Rebuild a time-of-use definition ("default rate + some windows") from the most recent full local day of prices."""
    df = pd.DataFrame(records)
    df["from"] = pd.to_datetime(df["valid_from"], utc=True).dt.tz_convert(TZ)
    df["to"] = pd.to_datetime(df["valid_to"], utc=True).dt.tz_convert(TZ)
    day = (pd.Timestamp.now(tz=TZ).normalize() - pd.Timedelta(days=1))
    slots = []
    for i in range(48):
        t = day + pd.Timedelta(minutes=30 * i)
        hit = df[(df["from"] <= t) & (df["to"] > t)]
        slots.append(round(float(hit.iloc[0]["value_inc_vat"]) / 100.0, 5))
    default = max(set(slots), key=slots.count)
    windows, i = [], 0
    while i < 48:
        if slots[i] == default:
            i += 1
            continue
        j = i
        while j < 48 and slots[j] == slots[i]:
            j += 1
        start, end = i * 30, j * 30
        windows.append(
            {
                "start": f"{start // 60:02d}:{start % 60:02d}",
                "end": f"{end // 60:02d}:{end % 60:02d}" if end < 1440 else "24:00",
                "rate": slots[i],
                "label": "cheap" if slots[i] < default else "peak",
            }
        )
        i = j
    return default, windows


def main(out_path: str) -> None:
    fetched = datetime.now(UTC)
    tariffs = []
    with httpx.Client(headers={"User-Agent": "wattgeist-tariff-snapshot"}) as c:
        def standing(product: str) -> float:
            return latest(fetch_all(c, f"{BASE}/{product}/electricity-tariffs/{tariff_code(product)}/standing-charges/"))

        flex = "VAR-22-11-01"
        rates = fetch_all(c, f"{BASE}/{flex}/electricity-tariffs/{tariff_code(flex)}/standard-unit-rates/")
        tariffs.append(
            {
                "id": "octopus-flexible", "name": "Flexible Octopus (single rate)", "kind": "flat",
                "unit_rate": latest(rates), "standing_charge_per_day": standing(flex),
                "notes": "A variable single-rate tariff that tracks the Ofgem price cap.",
            }
        )
        since = (fetched - timedelta(days=4)).isoformat()
        for product, tid, name, note in [
            ("GO-VAR-22-10-14", "octopus-go", "Octopus Go (EV night rate)", "Cheap electricity for five hours every night."),
            ("COSY-22-12-08", "octopus-cosy", "Cosy Octopus (heat pump)", "Three cheap windows a day and a 4pm to 7pm peak."),
        ]:
            recs = fetch_all(
                c, f"{BASE}/{product}/electricity-tariffs/{tariff_code(product)}/standard-unit-rates/",
                {"period_from": since},
            )
            default, windows = derive_windows(recs)
            tariffs.append(
                {
                    "id": tid, "name": name, "kind": "tou", "default_rate": default, "windows": windows,
                    "standing_charge_per_day": standing(product), "notes": note,
                }
            )

        agile = "AGILE-24-10-01"
        end = fetched.replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - timedelta(days=365)
        recs = fetch_all(
            c, f"{BASE}/{agile}/electricity-tariffs/{tariff_code(agile)}/standard-unit-rates/",
            {"period_from": start.isoformat(), "period_to": end.isoformat()},
        )
        df = pd.DataFrame(recs)
        ts = pd.to_datetime(df["valid_from"], utc=True).dt.tz_convert(TZ)
        price = df["value_inc_vat"].astype(float) / 100.0
        frame = pd.DataFrame(
            {"m": ts.dt.month - 1, "w": (ts.dt.day_of_week >= 5).astype(int), "s": ts.dt.hour * 2 + ts.dt.minute // 30, "p": price}
        )
        grid = frame.groupby(["m", "w", "s"])["p"].mean()
        overall = frame.groupby("s")["p"].mean()
        profile = np.zeros((12, 2, 48))
        for m in range(12):
            for w in range(2):
                for s in range(48):
                    profile[m, w, s] = grid.get((m, w, s), overall.get(s, float(price.mean())))
        tariffs.append(
            {
                "id": "octopus-agile", "name": "Agile Octopus (half-hourly prices)", "kind": "dynamic",
                "price_profile": np.round(profile, 5).tolist(), "standing_charge_per_day": standing(agile),
                "notes": (
                    f"Prices change every 30 minutes with the wholesale market. Over the last year they ranged "
                    f"from £{price.min():.2f} to £{price.max():.2f} per kWh and went negative "
                    f"{int((price < 0).sum())} times."
                ),
                "source": f"{len(price)} half-hourly prices from {start.date()} to {end.date()}",
            }
        )
    for t in tariffs:
        t.setdefault("currency", "GBP")
        t["source"] = (t.get("source", "") + "; " if t.get("source") else "") + (
            f"Octopus Energy public API, London region, direct debit, incl. VAT, fetched {fetched.date()}"
        )
    snapshot = {
        "fetched_at": fetched.isoformat(),
        "region": "London (C)",
        "source": "Octopus Energy public tariff API (api.octopus.energy)",
        "tariffs": tariffs,
    }
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, indent=1)
    for t in tariffs:
        print(t["id"], t.get("unit_rate") or t.get("default_rate"), t["standing_charge_per_day"], t.get("windows", "")[:3] if t.get("windows") else "")


if __name__ == "__main__":
    main(sys.argv[1])

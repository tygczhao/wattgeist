"""Load-shifting savings estimate ("what would moving the dishwasher to midnight save?").

Method: on the average day, move kwh_per_day of flexible use from the dearest slots to the cheapest.
The movable amount is capped: only the use above the always-on floor in a slot is people using power; the floor itself cannot move.
It is an average-day estimate, not a day-by-day schedule, and the UI labels it as one. A flat tariff always saves 0.
"""

from __future__ import annotations

import pandas as pd

from ..series import MeterSeries
from .engine import fill_missing, prices_for
from .models import Tariff


def shift_savings(series: MeterSeries, tariff: Tariff, kwh_per_day: float, always_on_w: float) -> dict:
    recent = series.last_days(365)
    filled = fill_missing(recent)
    prices = pd.Series(prices_for(tariff, filled.index, recent.interval_minutes), index=filled.index)
    slot = filled.index.hour * 60 + filled.index.minute
    avg_kwh = filled.groupby(slot).mean()
    avg_price = prices.groupby(slot).mean()
    floor_kwh = always_on_w / 1000.0 * recent.interval_hours
    flexible = (avg_kwh - floor_kwh).clip(lower=0.0)

    order = avg_price.sort_values(ascending=False).index
    cheapest = float(avg_price.min())
    remaining = max(0.0, kwh_per_day)
    saving_per_day = 0.0
    moved = 0.0
    for s in order:
        if remaining <= 1e-9:
            break
        take = min(remaining, float(flexible[s]))
        saving_per_day += take * (float(avg_price[s]) - cheapest)
        moved += take
        remaining -= take
    return {
        "tariff_id": tariff.id,
        "requested_kwh_per_day": round(kwh_per_day, 2),
        "shiftable_kwh_per_day": round(moved, 2),
        "annual_saving": round(max(0.0, saving_per_day) * 365.0, 2),
        "cheapest_slot": f"{int(avg_price.idxmin()) // 60:02d}:{int(avg_price.idxmin()) % 60:02d}",
        "currency": tariff.currency,
    }

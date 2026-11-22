"""Bill calculation.

Definition: take the last 365 days of use (or all, if shorter), fill missing intervals with the mean of the same day type and slot, then price every interval.
Filling keeps the comparison fair: without it more missing data means a cheaper bill, and gaps concentrated in one slot favour tariffs that are dear in that slot.
Every tariff is billed on the same filled series, so the ranking does not depend on how gaps are filled. Results are annualised to 365 days.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..series import MeterSeries
from .models import Tariff, hhmm_to_minutes


@dataclass
class Bill:
    tariff_id: str
    tariff_name: str
    currency: str
    annual_cost: float
    energy_cost: float
    standing_cost: float
    annual_kwh: float
    average_price: float
    days: float
    filled_share: float


def fill_missing(series: MeterSeries) -> pd.Series:
    """Usage in local time with gaps filled by the (weekday/weekend, slot) mean; 0 where that cell has no data either."""
    e = series.local_energy()
    key = pd.MultiIndex.from_arrays([e.index.day_of_week >= 5, e.index.hour * 60 + e.index.minute])
    profile = e.groupby(key).mean()
    fill = pd.Series(profile.reindex(key).to_numpy(), index=e.index)
    return e.fillna(fill).fillna(0.0)


def prices_for(tariff: Tariff, index: pd.DatetimeIndex, interval_minutes: int) -> np.ndarray:
    """Price every interval of a local-time index (currency per kWh). An interval is priced by the slot it starts in."""
    tariff.validate_complete()
    if tariff.kind == "flat":
        return np.full(len(index), float(tariff.unit_rate))
    minutes = (index.hour * 60 + index.minute).to_numpy()
    if tariff.kind == "tou":
        prices = np.full(len(index), float(tariff.default_rate))
        assigned = np.zeros(len(index), dtype=bool)
        dow = index.day_of_week.to_numpy()
        for w in tariff.windows:
            start, end = hhmm_to_minutes(w.start), hhmm_to_minutes(w.end)
            in_time = (minutes >= start) & (minutes < end) if start < end else (minutes >= start) | (minutes < end)
            hit = in_time & np.isin(dow, w.days) & ~assigned
            prices[hit] = w.rate
            assigned |= hit
        return prices
    profile = np.asarray(tariff.price_profile, dtype=float)  # [12][2][48]
    month = index.month.to_numpy() - 1
    weekend = (index.day_of_week.to_numpy() >= 5).astype(int)
    slot = minutes // 30
    if interval_minutes == 60:
        # Hourly data: use the mean price of the hour's two half-hour slots
        return (profile[month, weekend, slot] + profile[month, weekend, np.minimum(slot + 1, 47)]) / 2.0
    return profile[month, weekend, slot]


def compute_bill(series: MeterSeries, tariff: Tariff, window_days: int = 365) -> Bill:
    recent = series.last_days(window_days)
    filled = fill_missing(recent)
    filled_share = float(recent.energy_kwh.isna().mean())
    prices = prices_for(tariff, filled.index, recent.interval_minutes)
    energy_cost = float(np.sum(filled.to_numpy() * prices))
    days = (recent.end - recent.start).total_seconds() / 86400.0
    scale = 365.0 / days if days > 0 else 0.0
    kwh = float(filled.sum())
    annual_energy = energy_cost * scale
    standing = tariff.standing_charge_per_day * 365.0
    return Bill(
        tariff_id=tariff.id,
        tariff_name=tariff.name,
        currency=tariff.currency,
        annual_cost=round(annual_energy + standing, 2),
        energy_cost=round(annual_energy, 2),
        standing_cost=round(standing, 2),
        annual_kwh=round(kwh * scale, 1),
        average_price=round(energy_cost / kwh, 4) if kwh > 0 else 0.0,
        days=round(days, 1),
        filled_share=round(filled_share, 4),
    )


def slot_prices(tariff: Tariff) -> list[float]:
    """Year-average price per half-hour slot (48 points), for the frontend's "prices vs your usage" chart."""
    idx = pd.date_range("2025-01-01", "2025-12-31 23:30", freq="30min", tz="UTC")
    p = prices_for(tariff, idx, 30)
    return [round(float(v), 4) for v in pd.Series(p, index=idx).groupby(idx.hour * 60 + idx.minute).mean()]

"""Always-on (vampire) load estimation.

Definition: for each local calendar day take the lowest interval-average power (the "daily floor"), then the median of those floors.
- Daily minimum: late at night, once everyone is asleep, only routers, standby electronics and the fridge are drawing power; the minimum is their sum.
- Median: a night with a forgotten heater raises that day's minimum, but not the median. Such days are reported separately as haunted nights.
NRDC's 2015 analysis of about 70,000 Northern California homes also started from the smart meter minimum.
Half-hour averaging folds fridge and freezer compressor cycles into the floor, so they are included; the UI lists them as residents, separate from vampires you can switch off.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..series import MeterSeries

# A day counts only with at least 90% of its readings: the missing hours may be exactly the overnight trough, which would overstate the floor
MIN_DAY_COVERAGE = 0.9
# A day with this many zero readings (< 0.5 W) is treated as bad data (outage, meter fault, vacant and unpowered) and excluded.
# An occupied home with a fridge and a router practically never averages 0 W over half an hour
MAX_ZERO_SLOTS = 4
MIN_DAYS = 7
HOURS_PER_YEAR = 8760.0


class InsufficientData(ValueError):
    """Too few valid days to give a trustworthy always-on estimate."""


@dataclass
class HauntedNight:
    date: str
    floor_w: float
    excess_w: float
    # Lower bound on that day's extra energy: a floor excess_w above normal means every interval drew at least that much more
    extra_kwh: float


@dataclass
class AlwaysOnResult:
    watts: float
    annual_kwh: float
    share_of_consumption: float
    annual_consumption_kwh: float
    days_used: int
    days_excluded: int
    daily_floor_w: pd.Series = field(repr=False)
    monthly_floor_w: pd.Series = field(repr=False)
    haunted_nights: list[HauntedNight] = field(default_factory=list)
    # Each day's local baseline (rolling median); the frontend draws it next to the daily floor and haunted nights stand clearly above it
    baseline_w: pd.Series | None = field(default=None, repr=False)


def _valid_days(series: MeterSeries) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return (daily floor, daily energy, valid-day mask), all indexed by local date."""
    power = series.local_power_w()
    energy = series.local_energy()
    day = pd.Index(power.index.date, name="date")
    counts = power.groupby(day).count()
    floors = power.groupby(day).min()
    zeros = (power < 0.5).groupby(day).sum()
    daily_kwh = energy.groupby(day).sum(min_count=1)
    complete = counts >= series.slots_per_day * MIN_DAY_COVERAGE
    valid = complete & (zeros < MAX_ZERO_SLOTS)
    return floors, daily_kwh, valid


def estimate_always_on(series: MeterSeries, window_days: int = 365) -> AlwaysOnResult:
    """Estimate always-on load over the last window_days and find the haunted nights whose floor rose abnormally."""
    recent = series.last_days(window_days)
    floors, daily_kwh, valid = _valid_days(recent)
    good_floors = floors[valid]
    if len(good_floors) < MIN_DAYS:
        raise InsufficientData(
            f"Only {len(good_floors)} complete days of readings; at least {MIN_DAYS} are needed."
        )
    watts = float(good_floors.median())
    annual_consumption = float(daily_kwh[valid].mean() * 365.0)
    always_on_kwh = watts * HOURS_PER_YEAR / 1000.0
    share = min(1.0, always_on_kwh / annual_consumption) if annual_consumption > 0 else 0.0

    # Monthly floor: shows whether vampires multiplied over time (a new gadget, a replaced set-top box)
    month_index = pd.to_datetime(pd.Index(good_floors.index)).to_period("M")
    monthly = good_floors.groupby(month_index).median()

    # Haunted nights are compared with a rolling median of roughly four weeks either side (the local baseline), not with the yearly always-on value.
    # Winter heating or a dehumidifier lifts the floor for a whole season. That is seasonal (visible in the monthly trend), not a night someone forgot something;
    # a local baseline isolates the individual abnormal nights. The threshold is the largest of 3 x MAD, half the local baseline and 80 W,
    # so low-baseline homes are not flagged as haunted over a few watts of noise.
    dated = pd.Series(good_floors.to_numpy(), index=pd.to_datetime(pd.Index(good_floors.index)))
    baseline = dated.rolling("29D", center=True, min_periods=7).median().fillna(watts)
    resid = dated - baseline
    mad = float(resid.abs().median()) * 1.4826
    margin = np.maximum(np.maximum(3.0 * mad, 0.5 * baseline.to_numpy()), 80.0)
    threshold = baseline + margin
    excess = (dated - baseline)[dated > threshold].sort_values(ascending=False)
    nights = [
        HauntedNight(
            date=d.date().isoformat(),
            floor_w=round(float(dated[d]), 1),
            excess_w=round(float(x), 1),
            extra_kwh=round(float(x) * 24.0 / 1000.0, 2),
        )
        for d, x in excess.items()
    ]
    return AlwaysOnResult(
        watts=round(watts, 1),
        annual_kwh=round(always_on_kwh, 1),
        share_of_consumption=round(share, 4),
        annual_consumption_kwh=round(annual_consumption, 1),
        days_used=int(valid.sum()),
        days_excluded=int((~valid).sum()),
        daily_floor_w=good_floors,
        monthly_floor_w=monthly,
        haunted_nights=nights,
        baseline_w=pd.Series(baseline.to_numpy(), index=good_floors.index),
    )

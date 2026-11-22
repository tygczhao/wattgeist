"""Property tests (Hypothesis): invariants that must hold for any reasonable input.

The invariants map to requirement numbers in .kiro/specs; on failure Hypothesis shrinks the input to the smallest counterexample.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from wattgeist.analysis.always_on import estimate_always_on
from wattgeist.ingest.config import ParseConfig
from wattgeist.ingest.parse import parse_with_config
from wattgeist.series import MeterSeries, resample_energy
from wattgeist.tariffs.engine import compute_bill
from wattgeist.tariffs.models import Tariff, TouWindow

pytestmark = pytest.mark.property
FAST = settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])

TIMEZONES = ["UTC", "Europe/London", "America/New_York", "Australia/Sydney", "Asia/Kolkata", "Europe/Madrid"]


@st.composite
def readings(draw, min_days=8, max_days=20):
    """Random local start date, time zone, interval and energy per interval (0–3 kWh)."""
    tz = draw(st.sampled_from(TIMEZONES))
    interval = draw(st.sampled_from([15, 30, 60]))
    days = draw(st.integers(min_days, max_days))
    start = draw(st.dates(min_value=pd.Timestamp("2015-01-01").date(), max_value=pd.Timestamp("2030-12-01").date()))
    idx = pd.date_range(pd.Timestamp(start), periods=days * 1440 // interval, freq=f"{interval}min", tz=tz)
    seed = draw(st.integers(0, 2**31 - 1))
    rng = np.random.default_rng(seed)
    base = draw(st.floats(0.01, 0.5))
    values = (base * interval / 60 + rng.gamma(0.6, 0.15, len(idx)) * interval / 60).round(4)
    return pd.Series(values, index=idx), interval, tz


def _csv(series: pd.Series, *, unit: str = "kWh", marks: str = "start", reverse: bool = False) -> bytes:
    interval = pd.Timedelta(series.index.freq)
    # kW is the average power over the interval, so it is the energy divided by the interval length in hours,
    # which is only the same number as the energy for hourly data
    factor = {"kWh": 1.0, "Wh": 1000.0, "kW": 3600 / interval.total_seconds()}[unit]
    stamps = series.index + (interval if marks == "end" else pd.Timedelta(0))
    df = pd.DataFrame({"when": [t.isoformat() for t in stamps], "value": series.values * factor})
    if reverse:
        df = df.iloc[::-1]
    return df.to_csv(index=False).encode()


def _cfg(tz: str, unit: str = "kWh", marks: str = "start") -> ParseConfig:
    return ParseConfig(
        file_kind="csv", delimiter=",", timestamp_column="when", value_column="value",
        unit=unit, timestamp_marks=marks, timezone=tz,
    )


# meter-import Property 1 (energy is conserved by parsing)
# Requirements 1.4, 2.1 and 2.2: parsing preserves total energy for any unit, timestamp marking and row order
@FAST
@given(readings(), st.sampled_from(["kWh", "Wh", "kW"]), st.sampled_from(["start", "end"]), st.booleans())
def test_parsing_conserves_energy(r, unit, marks, reverse):
    series, _interval, tz = r
    result = parse_with_config(_csv(series, unit=unit, marks=marks, reverse=reverse), _cfg(tz, unit, marks))
    assert result.series.energy_kwh.sum() == pytest.approx(series.sum(), rel=1e-6, abs=1e-6)


# meter-import Property 2 (the canonical grid is well formed)
# Requirements 1.5, 2.2 and 2.3: fixed-interval, UTC, unique, starting at the true interval start (stamps marking start or end)
@FAST
@given(readings(), st.sampled_from(["start", "end"]))
def test_canonical_grid(r, marks):
    series, interval, tz = r
    s = parse_with_config(_csv(series, marks=marks), _cfg(tz, marks=marks)).series
    idx = s.energy_kwh.index
    assert str(idx.tz) == "UTC"
    assert idx.is_unique and idx.is_monotonic_increasing
    assert (idx[1:] - idx[:-1] == pd.Timedelta(minutes=s.interval_minutes)).all()
    assert idx[0] == series.index[0].tz_convert("UTC").floor(f"{s.interval_minutes}min")


# meter-import Property 3 (combining intervals never under-counts)
# Requirement 1.6: a bucket with any missing part is missing as a whole and never partially summed
@FAST
@given(readings(), st.data())
def test_resample_conservative_on_gaps(r, data):
    series, interval, _tz = r
    if interval != 15:
        return
    utc = series.tz_convert("UTC")
    drop = data.draw(st.lists(st.integers(0, len(utc) - 1), max_size=30, unique=True))
    gappy = utc.copy()
    gappy.iloc[drop] = np.nan
    out = resample_energy(gappy, 15, 30)
    full = resample_energy(utc, 15, 30)
    present = out.dropna()
    assert (present == full[present.index]).all()
    assert out.isna().sum() >= len({utc.index[i].floor("30min") for i in drop})


# Requirement 2.3: always-on load is no higher than the largest daily mean power and no lower than the series minimum
@FAST
@given(readings())
def test_always_on_bounds(r):
    series, interval, tz = r
    s = MeterSeries(energy_kwh=series.tz_convert("UTC").asfreq(f"{interval}min"), interval_minutes=interval, timezone=tz)
    ao = estimate_always_on(s)
    p = s.local_power_w()
    assert p.min() - 0.1 <= ao.watts
    daily_mean = p.groupby(p.index.date).mean()
    assert ao.watts <= daily_mean.max() + 0.1
    assert 0 <= ao.share_of_consumption <= 1


# Requirement 2.4: adding the same power to every interval raises always-on load by the same watts (shift equivariance)
@FAST
@given(readings(), st.floats(1, 500))
def test_always_on_shift_equivariant(r, extra_w):
    series, interval, tz = r
    s1 = MeterSeries(energy_kwh=series.tz_convert("UTC").asfreq(f"{interval}min"), interval_minutes=interval, timezone=tz)
    shifted = series + extra_w / 1000 * interval / 60
    s2 = MeterSeries(energy_kwh=shifted.tz_convert("UTC").asfreq(f"{interval}min"), interval_minutes=interval, timezone=tz)
    assert estimate_always_on(s2).watts == pytest.approx(estimate_always_on(s1).watts + extra_w, abs=0.15)


# Requirement 3.2: bills are linear in price; a time-of-use tariff with one price everywhere bills the same as a flat tariff
@FAST
@given(readings(), st.floats(0.05, 0.6), st.floats(0.5, 3.0))
def test_bill_linear_and_tou_degenerates(r, rate, k):
    series, interval, tz = r
    s = MeterSeries(energy_kwh=series.tz_convert("UTC").asfreq(f"{interval}min"), interval_minutes=interval, timezone=tz)
    flat = Tariff(id="a", name="a", kind="flat", unit_rate=rate)
    flat_k = Tariff(id="b", name="b", kind="flat", unit_rate=rate * k)
    tou = Tariff(id="c", name="c", kind="tou", default_rate=rate, windows=[TouWindow(start="00:30", end="05:30", rate=rate)])
    b1, b2, b3 = compute_bill(s, flat), compute_bill(s, flat_k), compute_bill(s, tou)
    assert b2.energy_cost == pytest.approx(b1.energy_cost * k, rel=1e-6, abs=0.02)
    assert b3.energy_cost == pytest.approx(b1.energy_cost, rel=1e-9, abs=0.01)


# Requirement 3.3: a time-of-use bill lies between "everything at the lowest rate" and "everything at the highest rate"
@FAST
@given(readings(), st.floats(0.01, 0.2), st.floats(0.2, 0.8))
def test_tou_bill_bounded(r, cheap, dear):
    series, interval, tz = r
    s = MeterSeries(energy_kwh=series.tz_convert("UTC").asfreq(f"{interval}min"), interval_minutes=interval, timezone=tz)
    tou = Tariff(id="t", name="t", kind="tou", default_rate=dear, windows=[TouWindow(start="22:00", end="06:00", rate=cheap)])
    b = compute_bill(s, tou)
    lo = compute_bill(s, Tariff(id="l", name="l", kind="flat", unit_rate=cheap)).energy_cost
    hi = compute_bill(s, Tariff(id="h", name="h", kind="flat", unit_rate=dear)).energy_cost
    assert lo - 0.01 <= b.energy_cost <= hi + 0.01

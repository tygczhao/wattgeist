"""Always-on load estimation and haunted-night detection."""

from __future__ import annotations

import pandas as pd
import pytest

from tests import fixtures as fx
from wattgeist.analysis.always_on import InsufficientData, estimate_always_on
from wattgeist.series import MeterSeries


def _series(t: pd.Series) -> MeterSeries:
    return MeterSeries(energy_kwh=t.tz_convert("UTC").asfreq("30min"), interval_minutes=30, timezone=str(t.index.tz))


def test_floor_matches_known_base_load():
    t = fx.truth_series(floor_w=150.0)
    ao = estimate_always_on(_series(t))
    # Noise of 0–30 W only adds power, so each day's minimum lands around 150–155 W
    assert 150 <= ao.watts <= 158
    # annual_kwh comes from unrounded watts and watts is rounded to one decimal for display, allowing 0.1 W x 8.76 of rounding
    assert ao.annual_kwh == pytest.approx(ao.watts * 8.76, abs=1.0)
    assert 0 < ao.share_of_consumption < 1


def test_single_haunted_night_is_found():
    t = fx.truth_series(floor_w=100.0)
    night = pd.Timestamp("2024-06-12", tz="Europe/London")
    day = (t.index >= night) & (t.index < night + pd.Timedelta(days=1))
    t = t.copy()
    t[day] += 0.4 / 2  # 400 W more in every half hour that day: a heater left on, say
    ao = estimate_always_on(_series(t))
    dates = [n.date for n in ao.haunted_nights]
    assert dates == ["2024-06-12"]
    assert ao.haunted_nights[0].excess_w == pytest.approx(400, abs=20)


def test_seasonal_rise_is_not_haunted():
    t = fx.truth_series(floor_w=100.0).copy()
    winter = (t.index.month <= 2) | (t.index.month == 12)
    t[winter] += 0.15 / 2  # 150 W more for the whole winter (an electric blanket, a dehumidifier): visible in the monthly trend, never haunted
    ao = estimate_always_on(_series(t))
    assert len(ao.haunted_nights) <= 3
    assert ao.monthly_floor_w.max() - ao.monthly_floor_w.min() > 100


def test_zero_days_are_excluded():
    t = fx.truth_series(floor_w=100.0).copy()
    outage = (t.index >= pd.Timestamp("2024-02-01", tz="Europe/London")) & (
        t.index < pd.Timestamp("2024-02-15", tz="Europe/London")
    )
    t[outage] = 0.0  # two weeks of outage or meter fault: these days must not pull always-on load to 0
    ao = estimate_always_on(_series(t))
    assert ao.days_excluded >= 14
    assert ao.watts > 90


def test_needs_a_week_of_data():
    t = fx.truth_series(start="2024-01-01", end="2024-01-04 23:30")
    with pytest.raises(InsufficientData):
        estimate_always_on(_series(t))

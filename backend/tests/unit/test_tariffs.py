"""Bills and load-shifting."""

from __future__ import annotations

import pytest

from tests import fixtures as fx
from wattgeist.series import MeterSeries
from wattgeist.tariffs.engine import compute_bill, prices_for
from wattgeist.tariffs.models import Tariff, TouWindow
from wattgeist.tariffs.presets import preset_tariffs
from wattgeist.tariffs.shift import shift_savings


@pytest.fixture(scope="module")
def series() -> MeterSeries:
    t = fx.truth_series()
    return MeterSeries(energy_kwh=t.tz_convert("UTC").asfreq("30min"), interval_minutes=30, timezone="Europe/London")


def test_flat_bill_is_kwh_times_rate(series):
    t = Tariff(id="f", name="flat", kind="flat", unit_rate=0.25, standing_charge_per_day=0.5)
    b = compute_bill(series, t)
    assert b.energy_cost == pytest.approx(b.annual_kwh * 0.25, rel=1e-3)
    assert b.standing_cost == pytest.approx(182.5)


def test_tou_window_across_midnight(series):
    t = Tariff(
        id="n", name="night", kind="tou", default_rate=0.30,
        windows=[TouWindow(start="23:30", end="05:30", rate=0.08)],
    )
    idx = series.local_energy().index
    p = prices_for(t, idx, 30)
    hours = idx.hour * 60 + idx.minute
    assert (p[(hours >= 23 * 60 + 30) | (hours < 5 * 60 + 30)] == 0.08).all()
    assert (p[(hours >= 5 * 60 + 30) & (hours < 23 * 60 + 30)] == 0.30).all()


def test_tou_on_dst_change_day_uses_local_clock(series):
    t = Tariff(id="n", name="night", kind="tou", default_rate=0.30, windows=[TouWindow(start="00:30", end="05:30", rate=0.09)])
    idx = series.local_energy().index
    p = prices_for(t, idx, 30)
    # On the autumn DST day 01:00–01:59 happens twice, and both must get the cheap rate
    fall = (idx.date == __import__("datetime").date(2024, 10, 27)) & (idx.hour == 1)
    assert fall.sum() == 4
    assert (p[fall] == 0.09).all()


def test_presets_load_and_bill(series):
    tariffs = preset_tariffs()
    assert {t.kind for t in tariffs} == {"flat", "tou", "dynamic"}
    for t in tariffs:
        b = compute_bill(series, t)
        assert 0.05 < b.average_price < 0.6


def test_shift_never_exceeds_flexible_energy(series):
    t = next(t for t in preset_tariffs() if t.kind == "tou")
    big = shift_savings(series, t, 500.0, always_on_w=120.0)
    assert big["shiftable_kwh_per_day"] < 500
    assert big["shiftable_kwh_per_day"] <= series.local_energy().groupby(
        series.local_energy().index.date).sum().mean()


def test_flat_tariff_has_no_shift_saving(series):
    t = Tariff(id="f", name="flat", kind="flat", unit_rate=0.25)
    assert shift_savings(series, t, 3.0, 100.0)["annual_saving"] == 0

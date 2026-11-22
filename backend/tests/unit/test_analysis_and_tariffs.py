"""Deterministic example tests for the analysis and tariff layers."""

import gzip
from importlib import resources

import pandas as pd
import pytest

from tests.helpers import make_truth
from wattgeist.analysis import profile
from wattgeist.analysis.always_on import InsufficientData, estimate_always_on
from wattgeist.analysis.benchmark import compare
from wattgeist.analysis.suspects import catalogue, explain_floor
from wattgeist.ingest.pipeline import import_meter_file
from wattgeist.series import MeterSeries
from wattgeist.tariffs.engine import compute_bill, slot_prices
from wattgeist.tariffs.models import Tariff, TouWindow
from wattgeist.tariffs.presets import preset_by_id, preset_tariffs
from wattgeist.tariffs.shift import shift_savings


def series_of(t):
    return MeterSeries(energy_kwh=t.kwh, interval_minutes=t.interval, timezone=t.tz)


def test_always_on_recovers_the_floor():
    t = make_truth(days=60, floor_w=150)
    ao = estimate_always_on(series_of(t))
    # Daily floor = always-on load + that day's smallest noise, so the estimate sits slightly above 150 W but not far above
    assert 150 <= ao.watts <= 190
    assert 0 < ao.share_of_consumption < 1
    assert ao.days_used >= 58


def test_haunted_night_is_found_and_seasonal_rise_is_not():
    t = make_truth(days=90, floor_w=100, start="2024-01-01")
    kwh = t.kwh.copy()
    local = kwh.index.tz_convert(t.tz)
    # Day 40 has an extra 400 W heater all day: it must be a haunted night
    kwh[local.normalize() == pd.Timestamp("2024-02-09", tz=t.tz)] += 0.2
    # The last 30 days have the floor raised by 200 W (seasonal): those 30 days must not all be haunted
    kwh[local >= pd.Timestamp("2024-03-01", tz=t.tz)] += 0.1
    ao = estimate_always_on(MeterSeries(energy_kwh=kwh, interval_minutes=30, timezone=t.tz))
    dates = [n.date for n in ao.haunted_nights]
    assert "2024-02-09" in dates
    assert len(dates) <= 5
    night = next(n for n in ao.haunted_nights if n.date == "2024-02-09")
    assert 300 <= night.excess_w <= 500


def test_insufficient_data():
    t = make_truth(days=3)
    with pytest.raises(InsufficientData):
        estimate_always_on(series_of(t))


def test_profile_shapes():
    t = make_truth(days=20)
    s = series_of(t)
    hm = profile.heatmap(s)
    assert len(hm["slots"]) == 48 and len(hm["watts"]) == len(hm["dates"])
    day = profile.average_day(s)
    assert len(day["weekday_w"]) == 48
    # The evening peak (19:00) is clearly above 04:00
    assert day["weekday_w"][38] > day["weekday_w"][8]
    summ = profile.summary(s)
    assert summ["interval_minutes"] == 30 and summ["annualized_kwh"] > 0
    assert sum(m["kwh"] for m in profile.monthly(s)) == pytest.approx(t.kwh.sum(), rel=1e-3)


def test_benchmark_and_suspects_data_are_packaged():
    b = compare(80.0, 3100.0)
    assert b["population"] > 4000
    assert 40 <= b["always_on"]["percentile"] <= 60
    ids = {d["id"] for d in catalogue()["devices"]}
    assert {"tv", "set_top_box", "router", "fridge_freezer"} <= ids
    e = explain_floor(100.0, {"tv": 2, "router": 1, "unknown": 3})
    assert e["explained_w"] == pytest.approx(31.5)
    assert e["unexplained_w"] == pytest.approx(68.5)
    assert e["vampire_w"] == pytest.approx(26.0)


def test_flat_tou_and_dynamic_bills():
    t = make_truth(days=30)
    s = series_of(t)
    flat = Tariff(id="f", name="Flat", kind="flat", unit_rate=0.25, standing_charge_per_day=0.5)
    b = compute_bill(s, flat)
    assert b.energy_cost == pytest.approx(t.kwh.sum() * 0.25 * 365 / 30, rel=1e-3)
    assert b.standing_cost == pytest.approx(182.5)
    night = Tariff(id="n", name="Night", kind="tou", default_rate=0.30,
                   windows=[TouWindow(start="22:00", end="06:00", rate=0.10)])
    assert compute_bill(s, night).average_price < 0.30
    prices = slot_prices(night)
    assert prices[0] == pytest.approx(0.10) and prices[30] == pytest.approx(0.30)


def test_presets_snapshot_is_complete():
    ids = {t.id for t in preset_tariffs()}
    assert ids == {"octopus-flexible", "octopus-go", "octopus-cosy", "octopus-agile"}
    for t in preset_tariffs():
        t.validate_complete()
        assert t.currency == "GBP" and 0 < t.standing_charge_per_day < 2


def test_night_owl_demo_saves_on_a_night_tariff():
    demo = resources.files("wattgeist.data").joinpath("demo", "night-owl.csv.gz")
    o = import_meter_file(gzip.decompress(demo.read_bytes()), "night-owl.csv", "Europe/London")
    s = o.result.series
    flex = compute_bill(s, preset_by_id("octopus-flexible"))
    go = compute_bill(s, preset_by_id("octopus-go"))
    assert go.annual_cost < flex.annual_cost * 0.85
    shift = shift_savings(s, preset_by_id("octopus-go"), 2.0, estimate_always_on(s).watts)
    assert shift["cheapest_slot"] in {f"{h:02d}:{m:02d}" for h in range(0, 6) for m in (0, 30)}

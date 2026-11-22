"""End-to-end import of national export formats with heuristics only (no AI); the result must reproduce the truth."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tests import fixtures as fx
from wattgeist.analysis.always_on import estimate_always_on
from wattgeist.ingest.pipeline import import_meter_file


def _check(outcome, truth: pd.Series, *, interval: int, total_tol: float = 1e-3, floor_tol_w: float = 15.0):
    assert outcome.error is None, outcome.error
    r = outcome.result
    assert r.report.interval_minutes == interval
    assert r.report.score >= 95, r.report
    total = r.series.energy_kwh.sum()
    assert total == pytest.approx(truth.sum(), rel=total_tol)
    ao = estimate_always_on(r.series)
    true_floor = (truth / 0.5 * 1000).groupby(truth.index.date).min().median()
    if interval == 60:
        # Hourly data averages two half hours, so the floor is slightly higher than at 30-minute resolution
        true_floor = (truth.resample("60min").sum(min_count=2) * 1000).groupby(
            truth.resample("60min").sum(min_count=2).index.date).min().median()
    assert ao.watts == pytest.approx(true_floor, abs=floor_tol_w)
    return r


@pytest.fixture(scope="module")
def london():
    return fx.truth_series(tz="Europe/London")


def test_octopus_reverse_order_with_offsets(london):
    o = import_meter_file(fx.octopus_csv(london), "consumption.csv", "Europe/London")
    r = _check(o, london, interval=30)
    assert r.config.timestamp_column == "Start"
    # After parsing a newest-first file, the first interval is the truth's first interval
    assert r.series.energy_kwh.index[0] == london.index[0].tz_convert("UTC")
    assert r.series.energy_kwh.iloc[0] == pytest.approx(london.iloc[0])


def test_lcl_end_marked_gmt_timestamps(london):
    o = import_meter_file(fx.lcl_csv(london), "LCL-June2015v2_0.csv", "Europe/London")
    r = _check(o, london, interval=30)
    assert r.config.timestamp_marks == "end"
    # Summer (BST) must not shift by an hour either: a July interval matches the truth exactly
    probe = pd.Timestamp("2024-07-15 19:00", tz="Europe/London")
    assert r.series.energy_kwh[probe.tz_convert("UTC")] == pytest.approx(london[probe], abs=1e-3)


def test_pge_preamble_mixed_fuel_month_first():
    t = fx.truth_series(tz="America/Los_Angeles")
    o = import_meter_file(fx.pge_csv(t), "pge_electric_usage.csv", "America/Los_Angeles")
    r = _check(o, t, interval=60, total_tol=2e-3)
    # header_row counts non-blank lines: the blank line after 4 account lines does not count, so the header is line 4 (from 0)
    assert r.config.header_row == 4
    assert r.config.filter_column == "TYPE"
    assert r.config.datetime_format == "%m/%d/%Y %H:%M"


def test_wide_layout_day_first():
    # Wide tables come from regions without DST (such as Queensland), so use the Brisbane zone
    t = fx.truth_series(tz="Australia/Brisbane")
    o = import_meter_file(fx.wide_csv(t), "nem12_wide.csv", "Australia/Brisbane")
    r = _check(o, t, interval=30)
    assert r.config.layout == "wide"
    assert r.config.datetime_format == "%d/%m/%Y"


def test_cumulative_register_semicolon_decimal_comma():
    t = fx.truth_series(tz="Europe/Berlin")
    o = import_meter_file(fx.register_csv(t), "zaehler.csv", "Europe/Berlin")
    r = _check(o, t, interval=30, total_tol=2e-3)
    assert r.config.delimiter == ";"
    assert r.config.decimal == ","
    assert r.config.reading_type == "cumulative"


def test_period_index_hours_with_dst_days():
    t = fx.truth_series(tz="Europe/Madrid")
    o = import_meter_file(fx.period_index_csv(t), "consumos.csv", "Europe/Madrid")
    r = _check(o, t, interval=60, total_tol=2e-3)
    assert r.config.time_is_period_index
    # The spring DST day has 23 hours and the autumn one 25; after period-number conversion the UTC timeline has no duplicates or gaps
    assert r.report.duplicate_timestamps == 0
    assert r.report.coverage == pytest.approx(1.0, abs=1e-3)


def test_esb_hdf_kw_end_marked_ignores_export():
    """Irish ESB Networks HDF: average kW stamped at the interval end in Irish local time, newest first, export rows mixed in.

    Nothing in the column names gives the unit or marks the export rows: 'Read Value' is just a number and the unit and
    channel are inside the values of 'Read Type'. Reading the kW column as kWh doubles a half-hourly file's energy.
    """
    t = fx.truth_series(tz="Europe/Dublin")
    o = import_meter_file(fx.esb_hdf_csv(t), "HDF_99000012345678.csv", "Europe/Dublin")
    r = _check(o, t, interval=30, total_tol=2e-3, floor_tol_w=15.0)
    assert r.config.unit == "kW"
    assert r.config.timestamp_marks == "end"
    assert r.config.datetime_format == "%d-%m-%Y %H:%M"
    # The export channel shares its timestamps with the import channel, so dropping those rows is the only way
    # to avoid averaging exported solar into consumption
    assert r.config.filter_column == "Read Type"
    assert r.report.duplicate_timestamps == 0
    assert r.series.energy_kwh.index[0] == t.index[0].tz_convert("UTC")
    # Newest-first naive local stamps still land correctly either side of both DST changes
    for probe in ("2024-03-31 12:00", "2024-07-15 19:00", "2024-10-27 12:00"):
        ts = pd.Timestamp(probe, tz="Europe/Dublin")
        assert r.series.energy_kwh[ts.tz_convert("UTC")] == pytest.approx(t[ts], abs=1e-3)
    # The two 01:30 local half hours of the autumn change are written identically in the file and newest first;
    # each must keep its own UTC slot, so no reading is dropped or averaged with its twin
    assert r.report.timestamp_failures == 0
    assert r.report.coverage == pytest.approx(1.0, abs=1e-4)
    for repeated in ("2024-10-27 00:30", "2024-10-27 01:30"):
        ts = pd.Timestamp(repeated, tz="UTC")
        assert r.series.energy_kwh[ts] == pytest.approx(t[ts], abs=1e-3)


def test_excel_with_preamble_in_wh(london):
    o = import_meter_file(fx.excel_bytes(london), "meter.xlsx", "Europe/London")
    r = _check(o, london, interval=30)
    assert r.config.unit == "Wh"


def test_green_button_ignores_solar_export(london):
    o = import_meter_file(fx.green_button_xml(london), "gb.xml", "Europe/London")
    _check(o, london, interval=30, total_tol=2e-3)
    assert any("exported" in n for n in o.result.notes)


def test_green_button_rejects_external_entities():
    evil = (
        b'<?xml version="1.0"?><!DOCTYPE feed [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        b'<feed xmlns="http://www.w3.org/2005/Atom">&xxe;</feed>'
    )
    o = import_meter_file(evil, "evil.xml", "UTC")
    assert o.result is None
    assert o.error


def test_garbage_file_reports_error():
    o = import_meter_file(b"hello\nworld\n", "notes.txt", "UTC")
    assert o.result is None
    assert o.error


def test_cumulative_reset_is_treated_as_missing():
    t = fx.truth_series(start="2024-03-01", end="2024-03-31 23:30", tz="Europe/Berlin")
    raw = fx.register_csv(t).decode().splitlines()
    # Simulate a meter swap mid-month: the register restarts from a low value at one row
    header, rows = raw[0], raw[1:]
    cut = len(rows) // 2
    offset = float(rows[cut].split(";")[1].replace(",", "."))
    fixed = rows[:cut] + [
        f"{r.split(';')[0]};" + f"{float(r.split(';')[1].replace(',', '.')) - offset + 3.0:.4f}".replace(".", ",")
        for r in rows[cut:]
    ]
    o = import_meter_file("\n".join([header] + fixed).encode(), "z.csv", "Europe/Berlin")
    r = o.result
    assert r.report.cumulative_resets == 1
    assert not (r.series.energy_kwh.dropna() < 0).any()
    assert np.isnan(r.series.energy_kwh).sum() == 1


def test_end_marked_times_with_24_00():
    """A date column plus an interval-end time column, where the day's last interval is written 24:00 (not next-day 00:00)."""
    t = fx.truth_series(start="2024-01-01", end="2024-01-31 23:30", tz="Australia/Brisbane")
    lines = ["Date,Interval end,kWh"]
    for ts, v in t.items():
        end = ts + pd.Timedelta(minutes=30)
        hhmm = "24:00" if end.hour == 0 and end.minute == 0 else f"{end:%H:%M}"
        day = ts.strftime("%d/%m/%Y")
        lines.append(f"{day},{hhmm},{v:.5f}")
    o = import_meter_file("\n".join(lines).encode(), "au.csv", "Australia/Brisbane")
    r = o.result
    assert o.error is None, o.error
    assert r.config.timestamp_marks == "end"
    assert r.report.timestamp_failures == 0
    assert r.series.energy_kwh.sum() == pytest.approx(t.sum(), rel=1e-6)
    assert r.series.energy_kwh.index[0] == t.index[0].tz_convert("UTC")


def test_preamble_notes_set_unit_and_end_marks():
    """Uninformative column names (col_a/col_b/col_c): the unit and interval marking are only stated in the lines above the header."""
    t = fx.truth_series(start="2024-01-01", end="2024-02-29 23:30", tz="Europe/London")
    lines = [
        "Export generated by HomeHub v2.1 for property 4471",
        "Values are average watts over each half hour, stamped at the END of the half hour",
        "",
        "col_a,col_b,col_c",
    ]
    for ts, v in (t / 0.5 * 1000).items():
        lines.append(f"P4471,{ts + pd.Timedelta(minutes=30):%Y-%m-%d %H:%M},{v:.2f}")
    o = import_meter_file("\n".join(lines).encode(), "homehub.csv", "Europe/London")
    r = o.result
    assert r.config.unit == "W"
    assert r.config.timestamp_marks == "end"
    assert r.series.energy_kwh.sum() == pytest.approx(t.sum(), rel=1e-4)
    # Requirement 2.8 also asks that the user is told where these two conventions came from
    assert any("readings are in W" in n for n in o.notes)
    assert any("mark the end of each interval" in n for n in o.notes)


class _AgreeingAssistant:
    """Test double: returns a config different from the heuristic but with an equal score, to test the tie rule."""

    def __init__(self, update):
        self.update = update

    def propose(self, preview, columns, current, problems):
        return current.model_copy(update=self.update), ["changed by test assistant"]


def test_ai_wins_ties_only_when_heuristic_was_unsure(london):
    data = fx.octopus_csv(london)
    # The Octopus file has no ambiguity: an equal-score alternative from the AI must not replace the heuristic
    o = import_meter_file(data, "c.csv", "Europe/London", assistant=_AgreeingAssistant({"unit": "kWh"}))
    assert o.source == "heuristic"
    assert not o.ai_used


def test_ai_wins_tie_when_heuristic_reported_ambiguity():
    """The heuristic reported an ambiguity (it cannot tell which column holds readings), so an equal-score AI alternative is adopted."""
    t = fx.truth_series(start="2024-01-01", end="2024-02-29 23:30", tz="Europe/London")
    lines = ["col_a,col_b,col_c"] + [f"P1,{ts:%Y-%m-%d %H:%M},{v:.5f}" for ts, v in t.items()]
    data = "\n".join(lines).encode()
    plain = import_meter_file(data, "x.csv", "Europe/London")
    assert plain.inference.ambiguities
    o = import_meter_file(data, "x.csv", "Europe/London", assistant=_AgreeingAssistant({"timestamp_marks": "end"}))
    assert o.ai_used
    assert o.source == "ai"
    assert o.result.config.timestamp_marks == "end"

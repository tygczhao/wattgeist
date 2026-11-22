"""Test helpers: generate usage series with a known truth and render them in various utility export formats.

Import tests are round trips: truth series -> rendered in some export format -> full import pipeline -> compared with the truth.
The renderers deliberately cover real-world traps: account preambles, day/month order, split date and time, wide tables, register readings, Wh/kW units,
European decimal commas, newest-first order and Green Button XML.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Truth:
    """Truth: kWh per interval indexed by UTC interval start."""

    kwh: pd.Series
    interval: int
    tz: str


def make_truth(days: int = 10, interval: int = 30, tz: str = "Europe/London", start: str = "2024-03-25",
               seed: int = 0, floor_w: float = 120.0) -> Truth:
    """Usage with a daily pattern: always-on floor_w + morning and evening peaks + random noise, every interval above the always-on load."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(pd.Timestamp(start, tz=tz), periods=days * 1440 // interval, freq=f"{interval}min").tz_convert("UTC")
    local = idx.tz_convert(tz)
    hour = local.hour + local.minute / 60
    shape = 300 * np.exp(-((hour - 8) ** 2) / 2) + 900 * np.exp(-((hour - 19) ** 2) / 3)
    watts = floor_w + shape + rng.gamma(2.0, 40.0, len(idx))
    kwh = np.round(watts / 1000 * interval / 60, 4)
    return Truth(pd.Series(kwh, index=idx), interval, tz)


def _naive_local(t: Truth, marks: str = "start") -> pd.DatetimeIndex:
    idx = t.kwh.index
    if marks == "end":
        idx = idx + pd.Timedelta(minutes=t.interval)
    return idx.tz_convert(t.tz).tz_localize(None)


def render_long_csv(t: Truth, *, fmt: str = "%Y-%m-%d %H:%M", value_header: str = "Consumption (kWh)",
                    unit_factor: float = 1.0, ts_header: str = "Start", marks: str = "start",
                    delimiter: str = ",", decimal: str = ".", preamble: list[str] | None = None,
                    descending: bool = False, power: bool = False) -> bytes:
    """Long table: one reading per row. power=True writes average interval power (kW); unit_factor handles units such as Wh."""
    ts = _naive_local(t, marks)
    values = t.kwh.to_numpy() * unit_factor
    if power:
        values = values / (t.interval / 60)
    rows = list(zip(ts.strftime(fmt), values, strict=True))
    if descending:
        rows = rows[::-1]
    out = io.StringIO()
    for line in preamble or []:
        out.write(line + "\n")
    out.write(f"{ts_header}{delimiter}{value_header}{delimiter}Estimated\n")
    for s, v in rows:
        txt = f"{v:.6f}"
        if decimal == ",":
            txt = txt.replace(".", ",")
        out.write(f"{s}{delimiter}{txt}{delimiter}N\n")
    return out.getvalue().encode()


def render_split_csv(t: Truth) -> bytes:
    """US PG&E style: account preamble + TYPE/DATE/START TIME/END TIME/USAGE/UNITS/COST, with gas rows mixed in."""
    ts = _naive_local(t)
    end = ts + pd.Timedelta(minutes=t.interval - 1)
    out = io.StringIO()
    out.write("Name,Jane Doe\nAddress,\"1 Main St, Springfield\"\nAccount Number,12345\nService,Service 1\n\n")
    out.write("TYPE,DATE,START TIME,END TIME,USAGE,UNITS,COST,NOTES\n")
    for s, e, v in zip(ts, end, t.kwh.to_numpy(), strict=True):
        out.write(f"Electric usage,{s:%Y-%m-%d},{s:%H:%M},{e:%H:%M},{v:.4f},kWh,${v * 0.3:.2f},\n")
    out.write("Natural gas usage,2024-01-01,00:00,23:59,1.2,therms,$2.00,\n")
    return out.getvalue().encode()


def render_wide_csv(t: Truth, date_fmt: str = "%d/%m/%Y") -> bytes:
    """Wide table: one row per day, columns 00:30...24:00 (named by interval end). The truth must cover whole days in a zone without DST changes."""
    local = t.kwh.tz_convert(t.tz)
    n = 1440 // t.interval
    labels = [f"{(i + 1) * t.interval // 60:02d}:{(i + 1) * t.interval % 60:02d}" for i in range(n)]
    out = io.StringIO()
    out.write("MPAN,Date," + ",".join(labels) + "\n")
    for day, g in local.groupby(local.index.date):
        if len(g) != n:
            continue
        out.write(f"1012345678901,{pd.Timestamp(day):{date_fmt}}," + ",".join(f"{v:.4f}" for v in g) + "\n")
    return out.getvalue().encode()


def render_cumulative_csv(t: Truth, start_reading: float = 15234.5) -> bytes:
    """Cumulative register: each reading = start reading + the energy of all previous intervals."""
    ts = _naive_local(t)
    reading = start_reading + np.concatenate([[0.0], np.cumsum(t.kwh.to_numpy())])
    times = list(ts) + [ts[-1] + pd.Timedelta(minutes=t.interval)]
    out = io.StringIO()
    out.write("Read Time,Meter Reading (kWh)\n")
    for s, r in zip(times, reading, strict=True):
        out.write(f"{s:%Y-%m-%dT%H:%M:%S},{r:.4f}\n")
    return out.getvalue().encode()


def render_excel(t: Truth) -> bytes:
    local = _naive_local(t)
    df = pd.DataFrame({"Interval start": local, "Energy (kWh)": t.kwh.to_numpy()})
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        pd.DataFrame([["My energy export"], ["Generated for testing"]]).to_excel(xw, index=False, header=False, startrow=0)
        df.to_excel(xw, index=False, startrow=3)
    return buf.getvalue()


def render_green_button(t: Truth, power_of_ten: int = 0) -> bytes:
    """A minimal working ESPI Atom feed: UsagePoint, MeterReading, ReadingType (Wh), IntervalBlock."""
    start = t.kwh.index.astype("int64") // 10**9 if t.kwh.index.dtype.unit == "s" else (t.kwh.index - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta(seconds=1)
    readings = "".join(
        f"<espi:IntervalReading><espi:timePeriod><espi:duration>{t.interval * 60}</espi:duration>"
        f"<espi:start>{int(s)}</espi:start></espi:timePeriod><espi:value>{int(round(v * 1000 / 10**power_of_ten))}</espi:value>"
        f"</espi:IntervalReading>"
        for s, v in zip(start, t.kwh.to_numpy(), strict=True)
    )
    base = "https://utility.example/espi/1_1/resource/Subscription/1/UsagePoint/1"
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:espi="http://naesb.org/espi">
 <entry><link rel="self" href="{base}"/><content><espi:UsagePoint><espi:ServiceCategory><espi:kind>0</espi:kind></espi:ServiceCategory></espi:UsagePoint></content></entry>
 <entry><link rel="self" href="{base}/MeterReading/1"/><link rel="related" href="https://utility.example/espi/1_1/resource/ReadingType/7"/><link rel="related" href="{base}/MeterReading/1/IntervalBlock"/><content><espi:MeterReading/></content></entry>
 <entry><link rel="self" href="https://utility.example/espi/1_1/resource/ReadingType/7"/><content><espi:ReadingType><espi:accumulationBehaviour>4</espi:accumulationBehaviour><espi:flowDirection>1</espi:flowDirection><espi:powerOfTenMultiplier>{power_of_ten}</espi:powerOfTenMultiplier><espi:uom>72</espi:uom></espi:ReadingType></content></entry>
 <entry><link rel="self" href="{base}/MeterReading/1/IntervalBlock/1"/><link rel="up" href="{base}/MeterReading/1/IntervalBlock"/><content><espi:IntervalBlock>{readings}</espi:IntervalBlock></content></entry>
</feed>"""
    return xml.encode()


def expected_on_grid(t: Truth, analysis_interval: int) -> pd.Series:
    """The truth combined into the analysis interval (same rule as resample_energy)."""
    if analysis_interval == t.interval:
        return t.kwh
    return t.kwh.resample(f"{analysis_interval}min", origin="epoch").sum(min_count=analysis_interval // t.interval)

"""Meter file generators for tests: common national export formats derived from one truth series.

The truth is a local-time, 30-minute, interval-start-indexed kWh series. Each generator follows its format's real conventions,
so the tests check whether the parser can turn every convention back into the same truth.
"""

from __future__ import annotations

import io

import numpy as np
import pandas as pd


def truth_series(start="2024-01-01", end="2024-12-31 23:30", tz="Europe/London", seed=7, floor_w=120.0) -> pd.Series:
    """A regular household: base load floor_w, morning and evening peaks, bounded noise. Returns 30-minute kWh indexed in local time."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, end, freq="30min", tz=tz)
    h = idx.hour + idx.minute / 60
    w = floor_w + 900 * np.exp(-((h - 19) ** 2) / 4) + 500 * np.exp(-((h - 7.5) ** 2) / 1)
    w = w + rng.uniform(0, 30, len(idx))  # noise only adds power, so the true floor stays close to floor_w
    return pd.Series(w / 2000.0, index=idx).round(5)


def octopus_csv(t: pd.Series) -> bytes:
    """UK Octopus Energy export: leading spaces in column names, ISO 8601 with offsets, newest first."""
    df = pd.DataFrame(
        {
            " Consumption (kWh)": t.values,
            " Start": [x.isoformat() for x in t.index],
            " End": [(x + pd.Timedelta(minutes=30)).isoformat() for x in t.index],
        }
    ).iloc[::-1]
    return df.to_csv(index=False).encode()


def lcl_csv(t: pd.Series, lclid="MAC000123") -> bytes:
    """Low Carbon London dataset: GMT timestamps all year (no DST), interval-end marks, readings with surrounding spaces."""
    utc = t.tz_convert("UTC")
    lines = ["LCLid,stdorToU,DateTime,KWH/hh (per half hour) "]
    for ts, v in utc.items():
        end = ts + pd.Timedelta(minutes=30)
        lines.append(f"{lclid},Std,{end:%Y-%m-%d %H:%M:%S}.0000000, {v:.3f} ")
    return ("\n".join(lines) + "\n").encode()


def pge_csv(t: pd.Series) -> bytes:
    """US PG&E "Green Button Download" CSV: account preamble, mixed electricity and gas, month-first dates, hourly data, a cost column.

    Hourly values are the sum of the truth's two half hours; in these exports the repeated DST hour appears once per local clock hour.
    """
    hourly = t.resample("60min").sum(min_count=2)
    lines = ["Name,JANE DOE", "Address,1 ELM ST", "Account Number,1234567", "Service,Service 1", ""]
    lines.append("TYPE,DATE,START TIME,END TIME,USAGE,UNITS,COST,NOTES")
    for ts, v in hourly.items():
        lines.append(f"Electric usage,{ts:%m/%d/%Y},{ts:%H:%M},{ts:%H}:59,{v:.4f},kWh,${v * 0.31:.2f},")
        if ts.hour == 0:
            lines.append(f"Natural gas usage,{ts:%m/%d/%Y},00:00,23:59,1.2,therms,$2.10,")
    return "\n".join(lines).encode()


def wide_csv(t: pd.Series) -> bytes:
    """One row per day with 48 period columns (00:00...23:30), day-first dates. Only valid in zones without DST."""
    local = t.tz_localize(None)
    frame = pd.DataFrame({"v": local.values, "d": local.index.strftime("%d/%m/%Y"), "s": local.index.strftime("%H:%M")})
    pv = frame.pivot_table(index="d", columns="s", values="v", aggfunc="first", sort=False)
    pv.index.name = "Date"
    return pv.reset_index().to_csv(index=False).encode()


def register_csv(t: pd.Series) -> bytes:
    """German-style cumulative register: semicolon separated, decimal comma, day.month.year. The register at time x = energy used before x."""
    reg = t.cumsum().shift(1, fill_value=0.0) + 18234.5
    local = reg.index.tz_localize(None)
    # Only the decimal point in numbers becomes a comma; dots in dates stay
    lines = ["Zeitstempel;Zählerstand (kWh)"] + [
        f"{ts:%d.%m.%Y %H:%M};" + f"{v:.4f}".replace(".", ",") for ts, v in zip(local, reg.values, strict=True)
    ]
    return "\n".join(lines).encode()


def period_index_csv(t: pd.Series) -> bytes:
    """Spanish i-DE style: CUPS;Fecha;Hora;Consumo_kWh, where Hora is the hour number of the day (23 or 25 on DST days)."""
    hourly = t.resample("60min").sum(min_count=2)
    rows = ["CUPS;Fecha;Hora;Consumo_kWh;Metodo_obtencion"]
    for d, g in hourly.groupby(hourly.index.date):
        for i, v in enumerate(g.values, 1):
            rows.append(f"ES0031400000000000XX0F;{d:%d/%m/%Y};{i};" + f"{v:.4f}".replace(".", ",") + ";R")
    return "\n".join(rows).encode()


def excel_bytes(t: pd.Series) -> bytes:
    """Excel: one note line above the header, readings in Wh, local interval-start times."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as x:
        pd.DataFrame([["Meter export for 12 Acacia Road"]]).to_excel(x, index=False, header=False, startrow=0)
        pd.DataFrame(
            {
                "Reading start (local)": t.index.tz_localize(None).strftime("%Y-%m-%d %H:%M"),
                "Energy (Wh)": (t.values * 1000).round(2),
            }
        ).to_excel(x, index=False, startrow=3)
    return buf.getvalue()


def green_button_xml(t: pd.Series, solar_export: bool = True) -> bytes:
    """A minimal working ESPI feed: one electricity UsagePoint, consumption readings (Wh, powerOfTen=0), optionally an export reading set."""
    utc = t.tz_convert("UTC")

    def block(mr: str, values) -> str:
        readings = "".join(
            f"<espi:IntervalReading><espi:timePeriod><espi:duration>1800</espi:duration>"
            f"<espi:start>{int(ts.timestamp())}</espi:start></espi:timePeriod>"
            f"<espi:value>{int(round(v))}</espi:value></espi:IntervalReading>"
            for ts, v in values
        )
        return (
            f'<entry><link rel="self" href="{mr}/IntervalBlock/1"/><link rel="up" href="{mr}/IntervalBlock"/>'
            f'<content><espi:IntervalBlock>{readings}</espi:IntervalBlock></content></entry>'
        )

    up = "https://utility.example/espi/1_1/resource/Subscription/1/UsagePoint/1"
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom" xmlns:espi="http://naesb.org/espi">',
        f'<entry><link rel="self" href="{up}"/><content><espi:UsagePoint><espi:ServiceCategory><espi:kind>0</espi:kind>'
        "</espi:ServiceCategory></espi:UsagePoint></content></entry>",
        f'<entry><link rel="self" href="{up}/MeterReading/1"/>'
        '<link rel="related" href="https://utility.example/espi/1_1/resource/ReadingType/1"/>'
        "<content><espi:MeterReading/></content></entry>",
        '<entry><link rel="self" href="https://utility.example/espi/1_1/resource/ReadingType/1"/>'
        "<content><espi:ReadingType><espi:accumulationBehaviour>4</espi:accumulationBehaviour>"
        "<espi:flowDirection>1</espi:flowDirection><espi:powerOfTenMultiplier>0</espi:powerOfTenMultiplier>"
        "<espi:uom>72</espi:uom></espi:ReadingType></content></entry>",
        block(f"{up}/MeterReading/1", [(ts, v * 1000) for ts, v in utc.items()]),
    ]
    if solar_export:
        parts += [
            f'<entry><link rel="self" href="{up}/MeterReading/2"/>'
            '<link rel="related" href="https://utility.example/espi/1_1/resource/ReadingType/2"/>'
            "<content><espi:MeterReading/></content></entry>",
            '<entry><link rel="self" href="https://utility.example/espi/1_1/resource/ReadingType/2"/>'
            "<content><espi:ReadingType><espi:accumulationBehaviour>4</espi:accumulationBehaviour>"
            "<espi:flowDirection>19</espi:flowDirection><espi:powerOfTenMultiplier>0</espi:powerOfTenMultiplier>"
            "<espi:uom>72</espi:uom></espi:ReadingType></content></entry>",
            block(f"{up}/MeterReading/2", [(ts, 999) for ts, _ in list(utc.items())[:96]]),
        ]
    parts.append("</feed>")
    return "".join(parts).encode()


def esb_hdf_csv(t: pd.Series, mprn: str = "10012345678", serial: str = "99000012345678") -> bytes:
    """Irish ESB Networks HDF export: average power in kW over each half hour, stamped at the END of the interval.

    Conventions taken from a real export: Irish local wall clock as dd-mm-yyyy HH:MM (so the nonexistent spring hour
    has no rows and the repeated autumn hour appears twice), newest row first, decimal point, no preamble, and an
    'Active Export Interval (kW)' channel sharing the timestamps of 'Active Import Interval (kW)'. Only the import
    channel is consumption; the export channel is the household's solar sent to the grid.
    """
    local_end = t.index + pd.Timedelta(minutes=30)
    import_kw = t.to_numpy() / 0.5  # kWh per half hour -> average kW over the half hour
    hours = local_end.hour + local_end.minute / 60
    export_kw = 2.4 * np.exp(-((hours - 13.5) ** 2) / 6)  # a solar day: nothing is exported at night
    lines = ["MPRN,Meter Serial Number,Read Value,Read Type,Read Date and End Time"]
    for end, imp, exp in zip(local_end[::-1], import_kw[::-1], export_kw[::-1], strict=True):
        stamp = f"{end:%d-%m-%Y %H:%M}"
        lines.append(f"{mprn},{serial},{imp:.3f},Active Import Interval (kW),{stamp}")
        lines.append(f"{mprn},{serial},{exp:.3f},Active Export Interval (kW),{stamp}")
    return ("\n".join(lines) + "\n").encode()

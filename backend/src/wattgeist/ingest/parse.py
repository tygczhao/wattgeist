"""Parse a meter file deterministically from its import settings, producing a canonical MeterSeries and a parse report.

The order of steps is fixed; do not reorder them:
  1. Select rows (fuel filter, meter selection)
  2. Parse timestamps to UTC; parse values
  3. Infer the native interval
  4. Difference cumulative readings / move end-marked timestamps back to interval start
  5. Convert units to kWh per interval
  6. Remove duplicates, drop negative values
  7. Combine into the analysis interval and fill the missing-reading grid
Unit conversion must come after step 3: kW and W are average power, and turning them into energy needs the interval length.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..series import MeterSeries, choose_analysis_interval, resample_energy
from .config import ParseConfig
from .greenbutton import parse_green_button
from .numbers import localize_naive, parse_datetimes, to_numbers
from .table import ImportError_, read_table
from .validate import ParseReport, score_report

# How each unit converts to kWh. Power units are further multiplied by the interval length in hours
_ENERGY_FACTOR = {"kWh": 1.0, "Wh": 0.001, "MWh": 1000.0}
_POWER_FACTOR = {"kW": 1.0, "W": 0.001}


@dataclass
class ParseResult:
    series: MeterSeries
    report: ParseReport
    config: ParseConfig
    meter_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _require(df: pd.DataFrame, col: str | None, role: str) -> str:
    if not col:
        raise ImportError_(f"No {role} column was specified.")
    if col not in df.columns:
        raise ImportError_(f"Column '{col}' ({role}) is not in the file. Columns: {', '.join(df.columns)}")
    return col


def _select_rows(df: pd.DataFrame, cfg: ParseConfig) -> tuple[pd.DataFrame, list[str], str | None]:
    """Keep only electricity rows in mixed-fuel files, and only one meter in multi-meter files (the one with most rows by default)."""
    if cfg.filter_column and cfg.filter_value:
        col = _require(df, cfg.filter_column, "filter")
        df = df[df[col].str.lower().str.contains(cfg.filter_value.lower(), regex=False)]
        if df.empty:
            raise ImportError_(f"No rows where '{cfg.filter_column}' contains '{cfg.filter_value}'.")
    meter_ids: list[str] = []
    chosen = None
    if cfg.meter_id_column:
        col = _require(df, cfg.meter_id_column, "meter id")
        counts = df[col].value_counts()
        meter_ids = [str(m) for m in counts.index.tolist() if str(m)]
        chosen = cfg.meter_id or (meter_ids[0] if meter_ids else None)
        if chosen not in meter_ids:
            raise ImportError_(f"Meter '{chosen}' was not found in column '{col}'.")
        df = df[df[col] == chosen]
    return df, meter_ids, chosen


def _period_index_points(df: pd.DataFrame, cfg: ParseConfig) -> tuple[pd.Series, pd.Series, int]:
    """A date column plus a period-number column (from 1).

    Local midnight is converted to UTC first, then (period - 1) x interval of elapsed time is added:
    on DST days the local clock repeats or skips an hour, but time elapsed since midnight is always monotonic, so the UTC times never overlap.
    Without an explicit interval, the largest period number decides: 24 -> 60 minutes, 48 -> 30, 96 -> 15 (23/25 on DST days map the same way).
    """
    date_col = _require(df, cfg.date_column, "date")
    period = to_numbers(df[_require(df, cfg.time_column, "period")])
    if cfg.interval_minutes:
        interval = cfg.interval_minutes
    else:
        top = int(period.dropna().max()) if period.notna().any() else 0
        interval = {23: 60, 24: 60, 25: 60, 46: 30, 48: 30, 50: 30, 92: 15, 96: 15, 100: 15}.get(top)
        if interval is None:
            raise ImportError_("Could not work out the period length from the period numbers.")
    dates = parse_datetimes(df[date_col], cfg.datetime_format)
    if getattr(dates.dt, "tz", None) is not None:
        dates = dates.dt.tz_convert(cfg.timezone).dt.tz_localize(None)
    midnight_utc = localize_naive(dates.dt.normalize(), cfg.timezone)
    valid = period.notna() & (period >= 1) & (period == period.round())
    offsets = pd.to_timedelta((period.where(valid) - 1) * interval, unit="m")
    ts = midnight_utc + offsets
    values = to_numbers(df[_require(df, cfg.value_column, "value")], cfg.decimal)
    return ts, values, interval


def _long_points(df: pd.DataFrame, cfg: ParseConfig) -> tuple[pd.Series, pd.Series]:
    if cfg.timestamp_column:
        strings = df[_require(df, cfg.timestamp_column, "timestamp")]
    elif cfg.date_column and cfg.time_column:
        strings = df[_require(df, cfg.date_column, "date")] + " " + df[_require(df, cfg.time_column, "time")]
    else:
        raise ImportError_("Specify either a timestamp column or both a date column and a time column.")
    ts = localize_naive(parse_datetimes(strings, cfg.datetime_format), cfg.timezone)
    values = to_numbers(df[_require(df, cfg.value_column, "value")], cfg.decimal)
    return ts, values


def _wide_points(df: pd.DataFrame, cfg: ParseConfig) -> tuple[pd.Series, pd.Series, int]:
    """Expand a one-row-per-day wide table into a long one.

    The j-th period column (in time order) is the j-th interval of the day, starting at midnight + j x interval.
    Whether the column names mark starts (00:00...23:30) or ends (00:30...24:00), taking the j-th interval in order gives the same result,
    so wide tables ignore timestamp_marks.
    """
    date_col = _require(df, cfg.date_column or cfg.timestamp_column, "date")
    cols = cfg.wide_value_columns or []
    if len(cols) < 2:
        raise ImportError_("A wide layout needs the list of per-period columns.")
    for c in cols:
        _require(df, c, "period")
    interval = cfg.interval_minutes or (1440 // len(cols))
    dates = parse_datetimes(df[date_col], cfg.datetime_format)
    if getattr(dates.dt, "tz", None) is not None:
        dates = dates.dt.tz_convert(cfg.timezone).dt.tz_localize(None)
    dates = dates.dt.normalize()
    offsets = np.arange(len(cols), dtype="int64") * interval
    values = np.column_stack([to_numbers(df[c], cfg.decimal).to_numpy(dtype=float) for c in cols])
    base = np.repeat(dates.to_numpy(), len(cols))
    deltas = np.tile(offsets, len(df)).astype("timedelta64[m]")
    naive = pd.Series(base + deltas)
    naive[pd.isna(np.repeat(dates.to_numpy(), len(cols)))] = pd.NaT
    ts = localize_naive(naive, cfg.timezone)
    return ts, pd.Series(values.reshape(-1)), interval


def _mode_minutes(ts: pd.Series) -> int:
    diffs = ts.drop_duplicates().sort_values().diff().dropna()
    diffs = diffs[diffs > pd.Timedelta(0)]
    if diffs.empty:
        raise ImportError_("Need at least two distinct timestamps to work out the reading interval.")
    minutes = (diffs.dt.total_seconds() / 60.0).round().astype(int)
    return int(minutes.mode().iloc[0])


def _normalize(
    ts: pd.Series,
    values: pd.Series,
    cfg: ParseConfig,
    report: ParseReport,
    *,
    shift_end_marks: bool,
    native_interval: int | None,
    cumulative: bool,
) -> pd.Series:
    """Pair timestamps with values, then infer the interval, difference, convert units, deduplicate and grid; returns kWh on the analysis interval."""
    ts = ts.reset_index(drop=True)
    values = values.reset_index(drop=True)
    report.timestamp_failures = int(ts.isna().sum())
    report.value_failures = int((values.isna() & ts.notna()).sum())
    frame = pd.DataFrame({"ts": ts, "v": values}).dropna().sort_values("ts", kind="stable")
    if len(frame) < 2:
        raise ImportError_("Fewer than two readings could be parsed with these settings.")

    native = native_interval or cfg.interval_minutes or _mode_minutes(frame["ts"])
    if native <= 0:
        raise ImportError_("Could not determine the reading interval.")
    step = pd.Timedelta(minutes=native)
    uniq = frame["ts"].drop_duplicates()
    gaps = uniq.diff().dropna()
    report.regularity = float((gaps == step).mean()) if len(gaps) else 0.0
    report.native_interval_minutes = native

    if cumulative:
        # A cumulative reading is the register at an instant: the difference between two readings is the energy between them, assigned to the interval that starts at the earlier one.
        # If two readings are not exactly one interval apart (missing data in between) the energy cannot be split per interval, so it is missing; a negative difference means a meter swap or wrap, also missing.
        frame = frame.drop_duplicates("ts", keep="last")
        dv = frame["v"].diff()
        dt = frame["ts"].diff()
        dv[dt != step] = np.nan
        report.cumulative_resets = int((dv < 0).sum())
        dv[dv < 0] = np.nan
        frame = pd.DataFrame({"ts": frame["ts"].shift(1), "v": dv}).iloc[1:]
    elif shift_end_marks and cfg.timestamp_marks == "end":
        frame["ts"] = frame["ts"] - step

    unit = cfg.unit
    if unit in _ENERGY_FACTOR:
        frame["kwh"] = frame["v"] * _ENERGY_FACTOR[unit]
    else:
        frame["kwh"] = frame["v"] * _POWER_FACTOR[unit] * (native / 60.0)

    report.duplicate_timestamps = int(len(frame) - frame["ts"].nunique())
    # Rows sharing a timestamp (concatenated exports, an autumn DST hour read as the same instant) are averaged: identical duplicates are unchanged, conflicting ones meet in the middle
    series = frame.dropna(subset=["ts"]).groupby("ts")["kwh"].mean()
    report.negative_values = int((series < 0).sum())
    if report.negative_values:
        report.warnings.append(
            f"{report.negative_values} negative readings were treated as missing (exported solar energy?)."
        )
    series = series.where(series >= 0)
    report.rows_used = int(series.notna().sum())

    analysis = choose_analysis_interval(native)
    if analysis != native:
        report.warnings.append(f"{native}-minute readings were combined into {analysis}-minute intervals.")
    if analysis == native:
        # At the same resolution resample only completes the grid: empty buckets become NaN and off-grid timestamps fall into their bucket
        grid = series.resample(f"{analysis}min", origin="epoch", label="left", closed="left").sum(min_count=1)
    else:
        grid = resample_energy(series, native, analysis)
    report.interval_minutes = analysis
    return grid.astype(float)


def parse_with_config(
    data: bytes, cfg: ParseConfig, analysis_timezone: str | None = None, label: str = ""
) -> ParseResult:
    """Parse a whole file with a config.

    analysis_timezone is where the household is, used by later analysis; cfg.timezone is the zone of the file's naive timestamps.
    They can differ: Low Carbon London timestamps are GMT all year (cfg.timezone=UTC),
    while night windows and time-of-use analysis must use London local time (Europe/London).
    """
    tz = analysis_timezone or cfg.timezone
    report = ParseReport()
    notes: list[str] = []
    meter_ids: list[str] = []
    chosen: str | None = None

    if cfg.file_kind == "greenbutton_xml":
        gb = parse_green_button(data)
        notes.extend(n for n in gb.notes if n != "cumulative")
        pts = gb.points
        report.rows_total = len(pts)
        native = int(round(pts["duration_s"].mode().iloc[0] / 60.0))
        grid = _normalize(
            pts["ts"],
            pts["kwh"],
            cfg.model_copy(update={"unit": "kWh"}),
            report,
            shift_end_marks=False,
            native_interval=native,
            cumulative="cumulative" in gb.notes,
        )
    else:
        df = read_table(data, cfg)
        df, meter_ids, chosen = _select_rows(df, cfg)
        report.rows_total = len(df)
        if cfg.layout == "wide":
            ts, values, interval = _wide_points(df, cfg)
            report.rows_total = len(values)
            grid = _normalize(
                ts, values, cfg, report, shift_end_marks=False, native_interval=interval, cumulative=False
            )
        elif cfg.time_is_period_index:
            ts, values, interval = _period_index_points(df, cfg)
            grid = _normalize(
                ts, values, cfg, report, shift_end_marks=False, native_interval=interval,
                cumulative=cfg.reading_type == "cumulative",
            )
        else:
            ts, values = _long_points(df, cfg)
            grid = _normalize(
                ts,
                values,
                cfg,
                report,
                shift_end_marks=True,
                native_interval=None,
                cumulative=cfg.reading_type == "cumulative",
            )

    series = MeterSeries(
        energy_kwh=grid, interval_minutes=report.interval_minutes, timezone=tz, meter_id=chosen, label=label
    )
    report.coverage = round(series.coverage(), 4)
    local = series.local_energy()
    report.start = local.index[0].isoformat()
    report.end = (local.index[-1] + pd.Timedelta(minutes=series.interval_minutes)).isoformat()
    report.days = round((series.end - series.start).total_seconds() / 86400.0, 2)
    med = grid.median()
    report.median_power_w = round(float(med / series.interval_hours * 1000.0), 1) if pd.notna(med) else 0.0
    report.score = score_report(report)
    return ParseResult(series=series, report=report, config=cfg, meter_ids=meter_ids, notes=notes)

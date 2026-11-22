"""Heuristic inference of the import settings.

The goal is to read mainstream export formats without AI. Anything it cannot infer, or finds ambiguous, goes into ambiguities
for the Kiro Crew format reviewer (llm/parse_assist.py) or for the user to confirm in the UI.
Inference only looks at the first INFER_SAMPLE_ROWS rows; parse.py then parses the whole file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from .config import ParseConfig, Unit
from .numbers import DATE_FORMATS, DATETIME_FORMATS, DAYFIRST_PAIRS, TIME_FORMATS, parse_datetimes, to_numbers
from .table import detect_file_kind, find_header_row, read_table, sniff_rows

INFER_SAMPLE_ROWS = 20000
_DT_SAMPLE = 400

# Keywords and weights for the reading column; columns matching the negative pattern (cost, temperature, ids, export...) are never chosen
_VALUE_POS = [
    (r"kwh", 6),
    (r"consum", 5),
    (r"usage", 5),
    (r"import", 4),
    (r"energy", 4),
    (r"deliver", 3),
    (r"(?<![a-z])wh(?![a-z])", 3),
    (r"(?<![a-z])kw(?![a-z])", 3),
    (r"demand", 2),
    (r"power", 2),
    (r"value", 2),
    (r"read", 2),
    (r"quantity|qty", 2),
    (r"load", 2),
    (r"/hh|(?<![a-z])hh(?![a-z])", 1),
    (r"total", 1),
]
_VALUE_NEG = re.compile(
    r"cost|price|charge|£|\$|€|tariff|temp|(?<![a-z])id(?![a-z])|lclid|number|count|quality|flag|status|"
    r"estimat|export|generat|solar|reactive|kvar|gas|co2|carbon|rate|unit",
    re.I,
)
_METER_NAME = re.compile(
    r"lclid|meter|mpan|mprn|esiid|serial|account|device|channel|premise|household|(?<![a-z])id(?![a-z])", re.I
)
# A row-label column says what each row is ("TYPE", "Read Type", "Energy type"); a leading word is allowed because
# exports name it after the reading ("Read Type") as often as not
_FILTER_NAME = re.compile(r"^(?:[\w ]*\s)?(type|kind|fuel|service|commodity|utility|direction)$", re.I)
# Row labels worth keeping, best first: only electricity drawn from the grid is consumption. Gas is another fuel and
# an export or generation channel is energy leaving the house, so neither may be counted or averaged into a reading
_KEEP_ROWS = ("elec", "import", "consum", "deliver")
_UNITS_COL = re.compile(r"^(units?|uom|unit of measure)$", re.I)
_TIME_NAME = re.compile(r"^(\d{1,2}):?(\d{2})(?::00)?$")
_RANGE_NAME = re.compile(r"^(\d{1,2}):(\d{2})(?::00)?\s*(?:-|–|~|to)\s*(\d{1,2}):(\d{2})(?::00)?$", re.I)
_INDEX_NAME = re.compile(r"^(?:hh|interval|int|period|p|sp|slot)\s*[_#\- ]?\s*(\d{1,3})$", re.I)
# Column names for "period number of the day" (English, Spanish, Portuguese, Italian, French, German). Values are integers 1..24 / 1..48 / 1..96
_PERIOD_COL_NAME = re.compile(
    r"^(hour|hora|ora|heure|stunde|period|periodo|período|interval|settlement period|sp|hh|slot)(\s*\(.*\))?$", re.I
)


@dataclass
class Inference:
    config: ParseConfig
    notes: list[str] = field(default_factory=list)
    ambiguities: list[str] = field(default_factory=list)
    meter_ids: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)


@dataclass
class _DtProfile:
    kind: str  # datetime | date | time
    fmt: str | None
    alt_fmt: str | None = None  # a format that also parses with day and month swapped (ambiguous dates like 03/04/2024)


def _profile_datetime(col: pd.Series) -> _DtProfile | None:
    """Decide whether a column holds timestamps, dates or clock times, and find a format that parses at least 95% of the sample."""
    s = col[col != ""].head(_DT_SAMPLE)
    if s.empty:
        return None
    # Purely numeric columns are almost always readings; only 8-digit numbers (YYYYMMDD) can be dates
    if to_numbers(s).notna().mean() > 0.9 and not s.str.fullmatch(r"\d{8}").all():
        return None
    fmt: str | None = None
    # Read "24:00" as 00:00 while sniffing the format, otherwise a time column with a few 24:00 values is not recognised as one
    s = s.str.replace(r"^24:00(:00)?$", lambda m: "00:00" + (m.group(1) or ""), regex=True)
    parsed = parse_datetimes(s, None)
    if parsed.notna().mean() < 0.95:
        fmt = None
        parsed = None
        for candidate in DATETIME_FORMATS + DATE_FORMATS + TIME_FORMATS:
            p = pd.to_datetime(s, format=candidate, errors="coerce")
            if p.notna().mean() >= 0.95:
                fmt, parsed = candidate, p
                break
        if parsed is None:
            return None
    alt = None
    if fmt in DAYFIRST_PAIRS:
        other = DAYFIRST_PAIRS[fmt]
        if pd.to_datetime(s, format=other, errors="coerce").notna().mean() >= 0.95:
            alt = other
    if fmt in TIME_FORMATS:
        kind = "time"
    else:
        valid = parsed.dropna()
        local = valid.dt.tz_convert(None) if getattr(valid.dt, "tz", None) is not None else valid
        kind = "date" if (local == local.dt.normalize()).all() and local.duplicated().any() else "datetime"
        if fmt in DATE_FORMATS:
            kind = "date"
    return _DtProfile(kind=kind, fmt=fmt, alt_fmt=alt)


def _regularity(strings: pd.Series, fmt: str | None) -> float:
    """Share of consecutive gaps (in file order) equal to the most common gap. Day/month swapped dates jump around and score much lower."""
    ts = parse_datetimes(strings, fmt).dropna()
    d = ts.diff().dropna()
    if d.empty:
        return 0.0
    return float((d == d.mode().iloc[0]).mean())


def _resolve_dayfirst(strings: pd.Series, fmt: str, alt: str, timezone: str, notes: list[str], amb: list[str]) -> str:
    r1, r2 = _regularity(strings, fmt), _regularity(strings, alt)
    # Any difference decides it: with day and month swapped only the gaps at day boundaries jump,
    # so 15-minute data over 4 days has just 3 jumps and regularity differs by under 1%; a fixed threshold would call that a tie
    if abs(r1 - r2) > 1e-9:
        chosen = fmt if r1 > r2 else alt
        notes.append(f"Dates could be day-first or month-first; the timeline is regular with {chosen}.")
        return chosen
    # When the data cannot decide (e.g. only the first 12 days of each month), use regional habit: month first in the Americas, day first elsewhere
    chosen = alt if timezone.startswith("America/") else fmt
    amb.append(f"Day/month order is ambiguous; assumed {chosen} from the time zone.")
    return chosen


def _marks_from_name(name: str) -> str | None:
    n = name.lower()
    if re.search(r"(?<![a-z])end|ending|(?<![a-z])to(?![a-z])|until", n):
        return "end"
    if re.search(r"start|begin|(?<![a-z])from(?![a-z])", n):
        return "start"
    return None


def unit_from_text(text: str) -> Unit | None:
    """Find the unit in a column name or a units column value. Check kWh before kW and Wh, otherwise 'kwh' would be read as kW."""
    n = text.lower()
    if "mwh" in n:
        return "MWh"
    if "kwh" in n or "kw h" in n:
        return "kWh"
    if re.search(r"(?<![a-z])wh(?![a-z])", n):
        return "Wh"
    if re.search(r"(?<![a-z])kw(?![a-z])", n):
        return "kW"
    if re.search(r"(?<![a-z])(w|watts?)(?![a-z])", n):
        return "W"
    return None


def _value_score(name: str) -> int:
    if _VALUE_NEG.search(name):
        return -10
    return sum(w for pat, w in _VALUE_POS if re.search(pat, name, re.I))


def _detect_decimal(col: pd.Series, delimiter: str | None) -> str:
    s = col[col != ""].head(500)
    comma = s.str.fullmatch(r"-?\d+,\d+").mean()
    dot = s.str.fullmatch(r"-?\d+\.\d+").mean()
    return "," if comma > dot and delimiter != "," else "."


def _detect_meter(df: pd.DataFrame, profiles: dict) -> tuple[str | None, list[str]]:
    for c in df.columns:
        if profiles.get(c) or not _METER_NAME.search(c):
            continue
        s = df[c][df[c] != ""]
        if s.empty:
            continue
        nunique = s.nunique()
        if 1 <= nunique <= max(1, len(s) // 20):
            ids = [str(x) for x in s.value_counts().index.tolist()]
            return (c if len(ids) > 1 else None), ids
    return None, []


def _detect_filter(df: pd.DataFrame) -> tuple[str | None, str | None]:
    """Find a row-label column and the label that marks grid consumption.

    Mixed-fuel exports label rows "Electric usage" / "Natural gas usage"; exports from a house with solar label the
    channels instead ("Active Import Interval (kW)" / "Active Export Interval (kW)"). A label only becomes a filter
    when some rows match it and others do not, so a single-channel file is left alone.
    """
    for c in df.columns:
        if not _FILTER_NAME.match(c.strip()):
            continue
        values = [v for v in df[c].str.lower().unique().tolist() if v]
        if len(values) < 2:
            continue
        for term in _KEEP_ROWS:
            matched = [term in v for v in values]
            if any(matched) and not all(matched):
                return c, term
    return None, None


def _detect_wide(df: pd.DataFrame, profiles: dict) -> tuple[list[str], str, int] | None:
    """Detect a wide table with one row per day and one column per period; the column order in the file is the time order."""
    entries: list[tuple[str, str]] = []
    for c in df.columns:
        n = c.strip()
        if _RANGE_NAME.match(n):
            entries.append((c, "range"))
        elif (m := _TIME_NAME.match(n)) and int(m[1]) <= 24 and int(m[2]) < 60:
            entries.append((c, "time"))
        elif _INDEX_NAME.match(n):
            entries.append((c, "index"))
    if len(entries) < 24:
        return None
    kinds = pd.Series([k for _, k in entries]).mode().iloc[0]
    cols = [c for c, k in entries if k == kinds]
    if 1440 % len(cols) != 0:
        return None
    numeric = sum(to_numbers(df[c]).notna().mean() for c in cols) / len(cols)
    if numeric < 0.8:
        return None
    date_cols = [c for c, p in profiles.items() if p and p.kind in ("date", "datetime") and c not in cols]
    if not date_cols:
        return None
    return cols, date_cols[0], 1440 // len(cols)


def _looks_cumulative(values: pd.Series, name: str) -> bool:
    """Cumulative readings are almost monotonic non-decreasing; interval readings go up and down, with about half of the differences negative.

    There is no "last value above first value" requirement: after a meter swap or wrap-around the register starts again and can end lower,
    but the file is still cumulative; the few negative differences become missing values during parsing (see parse._normalize).
    """
    v = values.dropna()
    if len(v) < 10:
        return False
    d = v.diff().dropna()
    hint = re.search(r"read|register|index|cumulat|odometer|zählerstand|zaehlerstand|stand|lectura|lettura", name, re.I)
    threshold = 0.95 if hint else 0.995
    return (d >= 0).mean() >= threshold and (d > 0).mean() > 0.3


def _mode_interval(ts: pd.Series) -> int | None:
    d = ts.dropna().drop_duplicates().sort_values().diff().dropna()
    d = d[d > pd.Timedelta(0)]
    if d.empty:
        return None
    return int((d.dt.total_seconds() / 60).round().astype(int).mode().iloc[0])


def _lcl_preset(df: pd.DataFrame, base: ParseConfig) -> Inference | None:
    """Low Carbon London dataset: GMT timestamps all year (no DST shift); each value is the energy of the half hour before its timestamp."""
    value_col = next((c for c in df.columns if c.lower().startswith("kwh/hh")), None)
    if "LCLid" not in df.columns or "DateTime" not in df.columns or value_col is None:
        return None
    ids = [str(x) for x in df["LCLid"].value_counts().index.tolist()]
    cfg = base.model_copy(
        update=dict(
            timestamp_column="DateTime",
            value_column=value_col,
            unit="kWh",
            timestamp_marks="end",
            timezone="UTC",
            interval_minutes=30,
            meter_id_column="LCLid",
            meter_id=ids[0] if ids else None,
        )
    )
    return Inference(
        config=cfg,
        notes=[
            "Recognised the Low Carbon London smart meter format.",
            "Timestamps are GMT all year and mark the end of each half hour.",
        ],
        meter_ids=ids,
    )


def _preamble_hints(rows: list[list[str]], header_row: int) -> dict:
    """Lines above the header often state conventions such as "values are average watts" or "stamped at the end".

    They are used only when the column names give no unit or interval marking (column names win), and are recorded in notes so the user sees why.
    """
    text = " ".join(" ".join(r) for r in rows[:header_row]).lower()
    hints: dict = {}
    if not text.strip():
        return hints
    if re.search(r"\bkwh\b|kilowatt[- ]?hours?", text):
        hints["unit"] = "kWh"
    elif re.search(r"\bwh\b|watt[- ]?hours?", text):
        hints["unit"] = "Wh"
    elif re.search(r"\bkw\b|kilowatts?\b", text):
        hints["unit"] = "kW"
    elif re.search(r"\bwatts?\b|\bw\b", text):
        hints["unit"] = "W"
    if re.search(r"\b(end|ending)\b.{0,30}\b(interval|half[- ]hour|period|hour)|\b(interval|half[- ]hour|period)\b.{0,30}\bend", text):
        hints["timestamp_marks"] = "end"
    elif re.search(r"\b(start|beginning)\b.{0,30}\b(interval|half[- ]hour|period|hour)", text):
        hints["timestamp_marks"] = "start"
    return hints


def infer_config(data: bytes, filename: str | None, timezone: str) -> Inference:
    """Inference entry point. timezone is the household's zone and the default for timestamps without an offset."""
    kind = detect_file_kind(data, filename)
    if kind == "greenbutton_xml":
        return Inference(
            config=ParseConfig(file_kind=kind, timezone=timezone),
            notes=["Detected a Green Button (ESPI) XML feed: timestamps are UTC and units come from the file."],
        )
    rows, delim = sniff_rows(data, kind)
    header_row = find_header_row(rows)
    base = ParseConfig(file_kind=kind, delimiter=delim, header_row=header_row, timezone=timezone)
    df = read_table(data, base, max_rows=INFER_SAMPLE_ROWS)
    inference = _lcl_preset(df, base) or _infer_frame(df, base)
    inference.columns = list(df.columns)
    hints = _preamble_hints(rows, header_row)
    cfg = inference.config
    unit_from_columns = cfg.value_column and unit_from_text(cfg.value_column)
    marks_from_columns = (cfg.timestamp_column and _marks_from_name(cfg.timestamp_column)) or (
        cfg.time_column and _marks_from_name(cfg.time_column))
    update = {}
    if "unit" in hints and not unit_from_columns and hints["unit"] != cfg.unit:
        update["unit"] = hints["unit"]
        inference.notes.append(f"The notes above the header say the readings are in {hints['unit']}.")
        inference.ambiguities = [a for a in inference.ambiguities if "unit" not in a.lower()]
    if "timestamp_marks" in hints and not marks_from_columns and cfg.layout == "long" and hints["timestamp_marks"] != cfg.timestamp_marks:
        update["timestamp_marks"] = hints["timestamp_marks"]
        inference.notes.append(f"The notes above the header say timestamps mark the {hints['timestamp_marks']} of each interval.")
    if update:
        inference.config = cfg.model_copy(update=update)
    if header_row:
        inference.notes.insert(0, f"Skipped {header_row} line(s) of account details above the header.")
    return inference


def _infer_frame(df: pd.DataFrame, base: ParseConfig) -> Inference:
    notes: list[str] = []
    amb: list[str] = []
    profiles = {c: _profile_datetime(df[c]) for c in df.columns}
    meter_col, meter_ids = _detect_meter(df, profiles)
    filter_col, filter_val = _detect_filter(df)
    sub = df
    if filter_col:
        sub = sub[sub[filter_col].str.lower().str.contains(filter_val, regex=False)]
        notes.append(
            f"Kept only the rows whose '{filter_col}' contains '{filter_val}'; the rest is another fuel or energy "
            "sent back to the grid, not consumption."
        )
    if meter_col:
        sub = sub[sub[meter_col] == meter_ids[0]]
        notes.append(f"Found {len(meter_ids)} meters in column '{meter_col}'; showing the one with most readings.")

    update: dict = dict(
        meter_id_column=meter_col, meter_id=meter_ids[0] if meter_col else None,
        filter_column=filter_col, filter_value=filter_val,
    )

    wide = _detect_wide(sub, profiles)
    if wide:
        cols, date_col, interval = wide
        prof = profiles[date_col]
        fmt = prof.fmt
        if prof.alt_fmt:
            fmt = _resolve_dayfirst(sub[date_col], prof.fmt, prof.alt_fmt, base.timezone, notes, amb)
        unit = unit_from_text(" ".join(cols)) or _unit_from_labels(sub) or "kWh"
        notes.append(f"One row per day with {len(cols)} period columns ({interval}-minute readings).")
        update.update(
            layout="wide", date_column=date_col, wide_value_columns=cols, interval_minutes=interval,
            datetime_format=fmt, unit=unit, decimal=_detect_decimal(sub[cols[0]], base.delimiter),
        )
        return Inference(config=base.model_copy(update=update), notes=notes, ambiguities=amb, meter_ids=meter_ids)

    dt_cols = [c for c, p in profiles.items() if p and p.kind == "datetime"]
    date_cols = [c for c, p in profiles.items() if p and p.kind == "date"]
    time_cols = [c for c, p in profiles.items() if p and p.kind == "time"]
    order = {c: i for i, c in enumerate(df.columns)}
    by_start = lambda c: (_marks_from_name(c) == "end", order[c])  # noqa: E731  prefer a start column when one exists

    strings: pd.Series | None = None
    used: set[str] = set()
    if dt_cols:
        ts_col = sorted(dt_cols, key=by_start)[0]
        prof = profiles[ts_col]
        fmt = prof.fmt
        if prof.alt_fmt:
            fmt = _resolve_dayfirst(sub[ts_col], prof.fmt, prof.alt_fmt, base.timezone, notes, amb)
        strings = sub[ts_col]
        update.update(timestamp_column=ts_col, datetime_format=fmt, timestamp_marks=_marks_from_name(ts_col) or "start")
        used.add(ts_col)
    elif date_cols and time_cols:
        date_col = date_cols[0]
        time_col = sorted(time_cols, key=by_start)[0]
        strings = sub[date_col] + " " + sub[time_col]
        prof = _profile_datetime(strings)
        fmt = prof.fmt if prof else None
        if prof and prof.alt_fmt:
            fmt = _resolve_dayfirst(strings, prof.fmt, prof.alt_fmt, base.timezone, notes, amb)
        update.update(
            date_column=date_col, time_column=time_col, datetime_format=fmt,
            timestamp_marks=_marks_from_name(time_col) or "start",
        )
        used.update({date_col, time_col})
    elif date_cols and (period_col := _detect_period_index(sub, date_cols[0])):
        date_col = date_cols[0]
        prof = profiles[date_col]
        fmt = prof.fmt
        if prof.alt_fmt:
            fmt = _resolve_dayfirst(sub[date_col], prof.fmt, prof.alt_fmt, base.timezone, notes, amb)
        periods = to_numbers(sub[period_col]).dropna()
        interval = {24: 60, 25: 60, 23: 60, 48: 30, 50: 30, 46: 30, 96: 15, 100: 15, 92: 15}[int(periods.max())]
        notes.append(
            f"Column '{period_col}' numbers the {interval}-minute periods of each day (1 = the period starting at midnight)."
        )
        update.update(
            date_column=date_col, time_column=period_col, time_is_period_index=True,
            datetime_format=fmt, interval_minutes=interval,
        )
        used.update({date_col, period_col})
        # Period-number files have no full timestamps; unit and cumulative detection below use an approximate time built from date + period
        base_dates = parse_datetimes(sub[date_col], fmt)
        strings = None
        approx_ts = base_dates + pd.to_timedelta((to_numbers(sub[period_col]) - 1) * interval, unit="m")
    else:
        amb.append("No timestamp column could be identified.")

    used.update(c for c in (meter_col, filter_col) if c)
    candidates = []
    for c in df.columns:
        if c in used or profiles.get(c):
            continue
        ratio = to_numbers(sub[c]).notna().mean() if len(sub) else 0.0
        if ratio >= 0.5:
            candidates.append((_value_score(c) + (1 if ratio >= 0.9 else -2), -order[c], c))
    if not candidates:
        amb.append("No numeric reading column could be identified.")
        return Inference(config=base.model_copy(update=update), notes=notes, ambiguities=amb, meter_ids=meter_ids)
    candidates.sort(reverse=True)
    value_col = candidates[0][2]
    if candidates[0][0] <= 1 or (len(candidates) > 1 and candidates[1][0] == candidates[0][0]):
        amb.append(f"Not sure which column holds the readings; picked '{value_col}'.")
    decimal = _detect_decimal(sub[value_col], base.delimiter)
    values = to_numbers(sub[value_col], decimal)
    update.update(value_column=value_col, decimal=decimal)

    if strings is not None:
        ts_sample = parse_datetimes(strings, update.get("datetime_format"))
    elif update.get("time_is_period_index"):
        ts_sample = approx_ts  # noqa: F821  only assigned in the period-number branch
    else:
        ts_sample = None
    interval = update.get("interval_minutes") or (_mode_interval(ts_sample) if ts_sample is not None else None)

    unit = unit_from_text(value_col)
    if unit is None and (unit := _unit_from_labels(sub)):
        notes.append(f"No column name gives a unit; the file's own labels say the readings are in {unit}.")
    if unit is None:
        unit = "kWh"
        med = values.median()
        if interval and pd.notna(med) and med / (interval / 60) * 1000 > 30000:
            unit = "Wh"
            notes.append("Readings are too large to be kWh for a home; treating them as Wh.")
        else:
            amb.append("The file does not state a unit; assumed kWh per interval.")
    update["unit"] = unit

    if ts_sample is not None:
        # Both columns share sub's row index, so align by index; .values would drop the time zone
        ordered = pd.DataFrame({"t": ts_sample, "v": values}).dropna().sort_values("t")["v"]
        if _looks_cumulative(ordered, value_col):
            update["reading_type"] = "cumulative"
            notes.append("Readings only ever go up, so they are meter register totals; using the differences.")
    notes.append(f"Readings every {interval} minutes." if interval else "Could not work out the reading interval.")
    return Inference(config=base.model_copy(update=update), notes=notes, ambiguities=amb, meter_ids=meter_ids)


def _detect_period_index(df: pd.DataFrame, date_col: str) -> str | None:
    """Find a "period number of the day" column: a matching name, positive integers, a maximum equal to the periods per day, and no repeats within a day."""
    for c in df.columns:
        if c == date_col or not _PERIOD_COL_NAME.match(c.strip()):
            continue
        v = to_numbers(df[c])
        if v.notna().mean() < 0.95:
            continue
        v = v.dropna()
        if not ((v >= 1) & (v == v.round())).all():
            continue
        if int(v.max()) not in (23, 24, 25, 46, 48, 50, 92, 96, 100):
            continue
        per_day = df.loc[v.index].groupby(date_col)[c].nunique()
        rows_per_day = df.loc[v.index].groupby(date_col)[c].size()
        if (per_day == rows_per_day).mean() > 0.95:
            return c
    return None


def _unit_from_labels(df: pd.DataFrame) -> Unit | None:
    """The unit as stated in cell values rather than in a column name.

    Two places hold it: a dedicated units column ("UNITS" = kWh), or the row label itself
    ("Active Import Interval (kW)"), which is where half-hourly exports with a plain "Read Value" column state it.
    The units column is read first because it describes the reading column directly.
    Pass a frame already reduced to the rows being imported, so the mode is the kept channel's label.
    """
    for pattern in (_UNITS_COL, _FILTER_NAME):
        for c in df.columns:
            if not pattern.match(c.strip()):
                continue
            vals = df[c][df[c] != ""]
            if vals.empty:
                continue
            if unit := unit_from_text(str(vals.mode().iloc[0])):
                return unit
    return None

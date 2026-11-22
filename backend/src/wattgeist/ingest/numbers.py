"""Lenient number and timestamp parsing shared by inference and parsing, so both read values the same way."""

from __future__ import annotations

import re

import pandas as pd

# Only common unit suffixes and currency prefixes are stripped, never arbitrary letters.
# Stripping letters from a Low Carbon London household id like "MAC000002" would leave 2 and make the id column look numeric.
_UNIT_SUFFIX = re.compile(r"(?i)\s*(kwh|mwh|wh|kw|w)$")
_CURRENCY_PREFIX = re.compile(r"^[£$€¥]\s*")
_OFFSET_SUFFIX = re.compile(r"(?:Z|[+-]\d{2}:?\d{2})$")

# Date-time formats. Day-first and month-first formats come in pairs so inference can compare the two readings
DATETIME_FORMATS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y %I:%M %p",
    "%m/%d/%Y %I:%M:%S %p",
    "%d/%m/%y %H:%M",
    "%m/%d/%y %H:%M",
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y %H:%M",
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y %H:%M",
    "%d-%b-%Y %H:%M",
    "%d %b %Y %H:%M",
]
DATE_FORMATS = [
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d/%m/%y",
    "%m/%d/%y",
    "%d.%m.%Y",
    "%d-%m-%Y",
    "%d-%b-%Y",
    "%d %b %Y",
    "%Y%m%d",
]
TIME_FORMATS = ["%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M:%S %p"]

# Format pairs that differ only in day/month order, used to detect ambiguous dates like 03/04/2024
DAYFIRST_PAIRS = {
    "%d/%m/%Y %H:%M:%S": "%m/%d/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M": "%m/%d/%Y %H:%M",
    "%d/%m/%y %H:%M": "%m/%d/%y %H:%M",
    "%d/%m/%Y": "%m/%d/%Y",
    "%d/%m/%y": "%m/%d/%y",
}


def to_numbers(series: pd.Series, decimal: str = ".") -> pd.Series:
    """Parse a string column as floats; failures become NaN.

    With decimal="," dots are thousands separators and are removed before the comma becomes the decimal point (European 1.234,5);
    with decimal="." commas are thousands separators and are removed (1,234.5).
    """
    s = series.astype(str).str.strip()
    s = s.str.replace(_UNIT_SUFFIX, "", regex=True)
    s = s.str.replace(_CURRENCY_PREFIX, "", regex=True)
    s = s.str.replace(r"[\s ]", "", regex=True)
    if decimal == ",":
        s = s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    else:
        s = s.str.replace(",", "", regex=False)
    return pd.to_numeric(s, errors="coerce")


def has_offsets(strings: pd.Series) -> bool:
    """When most timestamps carry a UTC offset (+01:00 or Z), parse them with offsets and ignore the configured zone."""
    s = strings[strings != ""].head(200)
    return bool(len(s)) and s.str.contains(_OFFSET_SUFFIX, regex=True).mean() > 0.8


_END_OF_DAY = re.compile(r"(?:^|[\sT])24:00(?::00)?$")


def parse_datetimes(strings: pd.Series, fmt: str | None) -> pd.Series:
    """Parse timestamps with a format; fmt=None means ISO 8601. Inputs with offsets come back in UTC, others as naive times.

    Some exports write "24:00" for the end of a day's last interval (common in end-marked Australian and UK files).
    Python's strptime rejects hour 24, so those values are parsed as 00:00 and moved forward one day.
    """
    strings = strings.astype(str)
    eod = strings.str.contains(_END_OF_DAY, regex=True)
    if eod.any():
        fixed = strings.where(~eod, strings.str.replace(r"24:00(:00)?$", lambda m: "00:00" + (m.group(1) or ""), regex=True))
        parsed = _parse_datetimes(fixed, fmt)
        return parsed.where(~eod, parsed + pd.Timedelta(days=1))
    return _parse_datetimes(strings, fmt)


def _parse_datetimes(strings: pd.Series, fmt: str | None) -> pd.Series:
    if fmt is None:
        if has_offsets(strings):
            return pd.to_datetime(strings, format="ISO8601", errors="coerce", utc=True)
        return pd.to_datetime(strings, format="ISO8601", errors="coerce")
    return pd.to_datetime(strings, format=fmt, errors="coerce")


def localize_naive(ts: pd.Series, timezone: str) -> pd.Series:
    """Convert naive local timestamps to UTC.

    In the autumn DST change the same local hour occurs twice; ambiguous="infer" relies on time order to tell them apart,
    so newest-first files (many utilities export the latest reading first) are reversed before inferring.
    If inference fails it falls back to ambiguous="NaT", dropping that hour, which the report shows as timestamp failures.
    The skipped spring hour does not exist; nonexistent="shift_forward" moves it past the jump.
    """
    if getattr(ts.dt, "tz", None) is not None:
        return ts.dt.tz_convert("UTC")
    valid = ts.dropna()
    if valid.empty:
        return ts.dt.tz_localize("UTC")
    descending = len(valid) > 1 and (valid.diff().dropna() < pd.Timedelta(0)).mean() > 0.5
    ordered = valid.iloc[::-1] if descending else valid
    idx = pd.DatetimeIndex(ordered.values)
    try:
        loc = idx.tz_localize(timezone, ambiguous="infer", nonexistent="shift_forward")
    except (ValueError, TypeError):  # pandas 3 AmbiguousTimeError / NonExistentTimeError are ValueError subclasses
        loc = idx.tz_localize(timezone, ambiguous="NaT", nonexistent="shift_forward")
    localized = pd.Series(loc.tz_convert("UTC"), index=ordered.index)
    # Put values back by original row; rows that failed stay NaT, and reindex keeps the localised series' resolution
    return localized.reindex(ts.index)

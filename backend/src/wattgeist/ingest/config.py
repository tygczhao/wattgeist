"""Import settings: a description of how to read one meter export into a canonical series.

Both heuristic and LLM inference only ever produce this config; the parsing itself is deterministic code.
An AI guess therefore always passes through the same checks: a wrong guess yields a low score, never silently corrupted data.
"""

from __future__ import annotations

from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, field_validator

FileKind = Literal["csv", "excel", "greenbutton_xml"]
Unit = Literal["kWh", "Wh", "MWh", "kW", "W"]


class ParseConfig(BaseModel):
    """How to read one export file. Field meanings must match the explanation in the format-reviewer agent prompt
    (crew-app/wattgeist-night-watch/agents/format-reviewer.json)."""

    model_config = ConfigDict(extra="forbid")

    file_kind: FileKind
    # CSV delimiter; unused for Excel and XML
    delimiter: str | None = None
    # Excel sheet name; None means the first sheet
    sheet: str | None = None
    # Header row index, counted over the file's non-blank lines from 0 (account preamble lines count)
    header_row: int = 0
    # long: one reading per row; wide: one row per day with one column per period (common in UK and Australian exports)
    layout: Literal["long", "wide"] = "long"
    # long layout: a full timestamp column, or a date column plus a time column
    timestamp_column: str | None = None
    date_column: str | None = None
    time_column: str | None = None
    # The time column holds the period number of the day (from 1), not a clock time. Spanish exports use Hora=1..24 for the hour of the day,
    # with period 1 starting at local midnight. DST days have 23 or 25 periods, so compute "local midnight + elapsed time", never a clock hour
    time_is_period_index: bool = False
    value_column: str | None = None
    # wide layout: the period columns in time order; the date comes from date_column or timestamp_column
    wide_value_columns: list[str] | None = None
    # Value unit. kW / W are average power over the interval and must be multiplied by its length to give energy
    unit: Unit = "kWh"
    # interval: each row is the energy used in that interval; cumulative: meter register totals that need differencing
    reading_type: Literal["interval", "cumulative"] = "interval"
    # Whether a timestamp marks interval start or end. Low Carbon London marks the end; getting it wrong shifts every slot by one interval
    timestamp_marks: Literal["start", "end"] = "start"
    # None means infer from the most common gap between timestamps
    interval_minutes: int | None = None
    # Timestamps without a UTC offset are read in this IANA zone; timestamps with an offset ignore it
    timezone: str = "UTC"
    # strftime format; None means ISO 8601. With separate date and time columns the format applies to "date + space + time"
    datetime_format: str | None = None
    # Decimal separator; European exports often use a comma
    decimal: Literal[".", ","] = "."
    # Multi-meter files (one Low Carbon London file holds dozens of homes): select meter_id in this column
    meter_id_column: str | None = None
    meter_id: str | None = None
    # Keep rows whose filter_column contains filter_value (case-insensitive). Used for mixed-fuel files (PG&E exports carry gas and electricity)
    # and for files with one row per channel, where the export channel shares the import channel's timestamps (ESB-style "Active Import/Export Interval")
    filter_column: str | None = None
    filter_value: str | None = None

    @field_validator("timezone")
    @classmethod
    def _valid_timezone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown timezone: {v}") from exc
        return v

    @field_validator("delimiter")
    @classmethod
    def _single_char(cls, v: str | None) -> str | None:
        if v is not None and len(v) != 1:
            raise ValueError("delimiter must be a single character")
        return v

    @field_validator("interval_minutes")
    @classmethod
    def _positive_interval(cls, v: int | None) -> int | None:
        if v is not None and not (1 <= v <= 1440):
            raise ValueError("interval_minutes must be between 1 and 1440")
        return v

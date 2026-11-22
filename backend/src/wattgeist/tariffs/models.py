"""Tariff definitions.

Money is always in major currency units per kWh (pounds, dollars), never pence or cents, so the frontend and backend never disagree on scale.
Time windows are always the household's local time; DST days are handled naturally by the MeterSeries local index.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_HHMM = re.compile(r"^([01]\d|2[0-4]):([0-5]\d)$")


def hhmm_to_minutes(s: str) -> int:
    m = _HHMM.match(s)
    if not m:
        raise ValueError(f"time must be HH:MM, got {s!r}")
    minutes = int(m[1]) * 60 + int(m[2])
    if minutes > 1440:
        raise ValueError("time must be at most 24:00")
    return minutes


class TouWindow(BaseModel):
    """One time-of-use window. end <= start means it wraps midnight (e.g. 22:00–05:00)."""

    model_config = ConfigDict(extra="forbid")
    start: str
    end: str
    rate: float = Field(ge=-10, le=10)
    days: list[int] = Field(default_factory=lambda: list(range(7)))  # 0 = Monday
    label: str = ""

    @field_validator("start", "end")
    @classmethod
    def _check_time(cls, v: str) -> str:
        hhmm_to_minutes(v)
        return v


class Tariff(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    kind: Literal["flat", "tou", "dynamic"]
    currency: str = "GBP"
    standing_charge_per_day: float = Field(default=0.0, ge=0, le=100)
    # flat: a single unit rate
    unit_rate: float | None = Field(default=None, ge=-10, le=10)
    # tou: matching windows use their rate, everything else default_rate; with overlapping windows the first match in the list wins
    windows: list[TouWindow] = Field(default_factory=list)
    default_rate: float | None = Field(default=None, ge=-10, le=10)
    # dynamic: a typical price matrix [month 1–12][0 weekday / 1 weekend][half-hour slot 0–47], each cell the mean of real historical prices
    price_profile: list[list[list[float]]] | None = None
    source: str = ""
    notes: str = ""

    def validate_complete(self) -> None:
        """Check required fields by kind; this is an explicit method because the frontend allows incomplete states while editing a custom tariff."""
        if self.kind == "flat" and self.unit_rate is None:
            raise ValueError("a flat tariff needs unit_rate")
        if self.kind == "tou" and (self.default_rate is None or not self.windows):
            raise ValueError("a time-of-use tariff needs windows and default_rate")
        if self.kind == "dynamic":
            p = self.price_profile
            if not p or len(p) != 12 or any(len(d) != 2 or any(len(s) != 48 for s in d) for d in p):
                raise ValueError("a dynamic tariff needs a 12 x 2 x 48 price profile")

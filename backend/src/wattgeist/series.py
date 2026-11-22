"""The canonical meter series.

The backend has exactly one internal representation: fixed interval, UTC, indexed by interval start, energy (kWh) per interval.
The import layer turns every export format into it and the analysis and tariff layers only consume it,
so the most error-prone conventions (unit conversion, time zones, interval start vs end) are handled once, in import.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

# Canonical intervals supported by analysis (minutes).
# Data finer than 30 minutes (such as the 15-minute data common in the US) is combined into 30 minutes:
# the daily minimum power depends on resolution, so results from different sources only compare at one resolution.
# 60-minute data (common for US utilities) stays as it is; splitting it would invent information.
ANALYSIS_INTERVALS = (30, 60)


@dataclass(frozen=True)
class MeterSeries:
    """One canonical usage series.

    energy_kwh: indexed by UTC interval start at a fixed interval_minutes frequency; values are kWh per interval, NaN where missing.
    timezone: the household's IANA zone, used only for clock-dependent analysis (night windows, tariff windows, calendar days).
    It is not the zone of the source file's timestamps, which were already converted to UTC during import.
    """

    energy_kwh: pd.Series
    interval_minutes: int
    timezone: str
    meter_id: str | None = None
    label: str = ""

    @property
    def interval_hours(self) -> float:
        return self.interval_minutes / 60.0

    @property
    def slots_per_day(self) -> int:
        """Intervals per day (48 for 30-minute data). DST days really have one hour more or less, so grouping by calendar day must allow for it."""
        return 1440 // self.interval_minutes

    def local_energy(self) -> pd.Series:
        """Energy in the household's local time zone: only the index zone changes, the values do not."""
        return self.energy_kwh.tz_convert(self.timezone)

    def local_power_w(self) -> pd.Series:
        """Average power per interval (W) = interval kWh / interval hours x 1000."""
        return self.local_energy() / self.interval_hours * 1000.0

    @property
    def start(self) -> pd.Timestamp:
        return self.energy_kwh.index[0]

    @property
    def end(self) -> pd.Timestamp:
        """End of the covered range (exclusive): the last interval start plus one interval."""
        return self.energy_kwh.index[-1] + pd.Timedelta(minutes=self.interval_minutes)

    def coverage(self) -> float:
        """Share of intervals with a reading; missing intervals were filled with NaN during normalisation, so the denominator is the canonical grid length."""
        n = len(self.energy_kwh)
        return float(self.energy_kwh.notna().sum() / n) if n else 0.0

    def last_days(self, days: int) -> MeterSeries:
        """The most recent days, for "last year" annualised figures; returned unchanged when there is less data than that."""
        cutoff = self.end - pd.Timedelta(days=days)
        if self.start >= cutoff:
            return self
        return MeterSeries(
            energy_kwh=self.energy_kwh[self.energy_kwh.index >= cutoff],
            interval_minutes=self.interval_minutes,
            timezone=self.timezone,
            meter_id=self.meter_id,
            label=self.label,
        )


def resample_energy(energy: pd.Series, source_minutes: int, target_minutes: int) -> pd.Series:
    """Combine fine-grained energy into a coarser interval.

    A bucket is summed only when every sub-interval has a reading; otherwise the whole bucket is NaN.
    This is conservative: summing a half-empty bucket understates energy, which lowers the daily minimum and directly understates standby load.
    Bucket edges align to the epoch so 30-minute buckets fall on :00 / :30, matching time-of-use window boundaries.
    """
    if target_minutes % source_minutes != 0:
        raise ValueError(f"cannot resample {source_minutes}min data to {target_minutes}min")
    if target_minutes == source_minutes:
        return energy
    per_bucket = target_minutes // source_minutes
    return energy.resample(f"{target_minutes}min", origin="epoch", label="left", closed="left").sum(
        min_count=per_bucket
    )


def choose_analysis_interval(native_minutes: int) -> int:
    """Choose the analysis interval from the native one; intervals that do not divide 30 or 60 (such as 7 minutes) and data coarser than 60 minutes are rejected."""
    if native_minutes in ANALYSIS_INTERVALS:
        return native_minutes
    if native_minutes < 30 and 30 % native_minutes == 0:
        return 30
    if native_minutes < 60 and 60 % native_minutes == 0:
        return 60
    raise ValueError(
        f"{native_minutes}-minute data is not supported: WattGeist needs readings every 60 minutes or finer"
    )

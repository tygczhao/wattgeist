"""Usage profile: summary figures, time-of-day heatmap, average day, monthly use.

Everything grouped by clock time uses the household's local time (MeterSeries.timezone).
On the autumn DST day a local time occurs twice and the heatmap averages the two; the skipped spring hour shows as empty that day.
"""

from __future__ import annotations

import pandas as pd

from ..series import MeterSeries
from .always_on import MIN_DAY_COVERAGE


def _slot_labels(series: MeterSeries) -> list[str]:
    return [f"{m // 60:02d}:{m % 60:02d}" for m in range(0, 1440, series.interval_minutes)]


def _local_frame(series: MeterSeries) -> pd.DataFrame:
    p = series.local_power_w()
    return pd.DataFrame(
        {
            "w": p.values,
            "kwh": series.local_energy().values,
            "date": p.index.date,
            "slot": p.index.strftime("%H:%M"),
            "weekend": p.index.day_of_week >= 5,
            "month": p.index.strftime("%Y-%m"),
        }
    )


def summary(series: MeterSeries) -> dict:
    """Summary: data range, average daily use, annualised use, and the time of peak power."""
    f = _local_frame(series)
    by_day = f.groupby("date")
    counts = by_day["kwh"].count()
    complete = counts[counts >= series.slots_per_day * MIN_DAY_COVERAGE].index
    daily = by_day["kwh"].sum(min_count=1).loc[complete]
    peak_idx = f["w"].idxmax() if f["w"].notna().any() else None
    local = series.local_energy()
    return {
        "start": local.index[0].isoformat(),
        "end": (local.index[-1] + pd.Timedelta(minutes=series.interval_minutes)).isoformat(),
        "days": int(len(counts)),
        "complete_days": int(len(daily)),
        "coverage": round(series.coverage(), 4),
        "interval_minutes": series.interval_minutes,
        "timezone": series.timezone,
        "total_kwh": round(float(f["kwh"].sum()), 1),
        "avg_daily_kwh": round(float(daily.mean()), 2) if len(daily) else None,
        "annualized_kwh": round(float(daily.mean() * 365.0), 0) if len(daily) else None,
        "peak_w": round(float(f["w"].max()), 0) if peak_idx is not None else None,
        "peak_at": local.index[peak_idx].isoformat() if peak_idx is not None else None,
    }


def heatmap(series: MeterSeries, days: int = 365) -> dict:
    """Date x time-of-day matrix of average power (W, rounded) for the last days, None where missing. The frontend draws the calendar heatmap from it."""
    recent = series.last_days(days)
    f = _local_frame(recent)
    table = f.pivot_table(index="date", columns="slot", values="w", aggfunc="mean")
    slots = _slot_labels(recent)
    table = table.reindex(columns=slots)
    values = [[None if pd.isna(v) else int(round(v)) for v in row] for row in table.to_numpy()]
    return {"dates": [str(d) for d in table.index], "slots": slots, "watts": values}


def average_day(series: MeterSeries, days: int = 365) -> dict:
    """Average power by time of day (W) for weekdays and weekends."""
    f = _local_frame(series.last_days(days))
    slots = _slot_labels(series)

    def curve(mask) -> list[float | None]:
        s = f[mask].groupby("slot")["w"].mean().reindex(slots)
        return [None if pd.isna(v) else round(float(v), 1) for v in s]

    return {"slots": slots, "weekday_w": curve(~f["weekend"]), "weekend_w": curve(f["weekend"])}


def monthly(series: MeterSeries) -> list[dict]:
    """Energy per month with the share of readings present; the frontend fades low-coverage months so missing data is not read as savings."""
    f = _local_frame(series)
    out = []
    for month, g in f.groupby("month"):
        period = pd.Period(month, freq="M")
        expected = period.days_in_month * series.slots_per_day
        out.append(
            {
                "month": month,
                "kwh": round(float(g["kwh"].sum()), 1),
                "coverage": round(float(g["kwh"].count() / expected), 3),
            }
        )
    return out


def daily(series: MeterSeries) -> list[dict]:
    f = _local_frame(series)
    d = f.groupby("date")["kwh"].agg(["sum", "count"])
    return [
        {"date": str(k), "kwh": round(float(r["sum"]), 2), "complete": bool(r["count"] >= series.slots_per_day * 0.9)}
        for k, r in d.iterrows()
    ]


def day_detail(series: MeterSeries, date: str) -> dict:
    """Power through one day, so the assistant can look at what happened that day."""
    f = _local_frame(series)
    g = f[f["date"].astype(str) == date]
    if g.empty:
        return {"date": date, "found": False}
    return {
        "date": date,
        "found": True,
        "kwh": round(float(g["kwh"].sum()), 2),
        "min_w": round(float(g["w"].min()), 1),
        "max_w": round(float(g["w"].max()), 1),
        "slots": g["slot"].tolist(),
        "watts": [None if pd.isna(v) else round(float(v), 1) for v in g["w"]],
    }

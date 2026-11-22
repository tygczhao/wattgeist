"""Scoring a parse.

Heuristic and LLM configs are both actually parsed and compared with the same score.
The score is also shown to the user: a low score means "probably misread", and the UI asks the user to check columns and units.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ParseReport:
    rows_total: int = 0
    rows_used: int = 0
    timestamp_failures: int = 0
    value_failures: int = 0
    duplicate_timestamps: int = 0
    negative_values: int = 0
    cumulative_resets: int = 0
    native_interval_minutes: int = 0
    interval_minutes: int = 0
    regularity: float = 0.0  # share of consecutive gaps equal to the native interval, i.e. whether timestamps were understood
    coverage: float = 0.0  # share of the canonical grid that has a reading
    start: str = ""
    end: str = ""
    days: float = 0.0
    median_power_w: float = 0.0
    warnings: list[str] = field(default_factory=list)
    score: float = 0.0


# Plausible median household power (W). Outside this range a unit was almost always misread (Wh read as kWh is 1000x too big)
PLAUSIBLE_MEDIAN_W = (5.0, 15000.0)


def score_report(r: ParseReport) -> float:
    """0–100: points are deducted for parse failures, missing coverage, irregular timestamps and implausible power."""
    if r.rows_total == 0 or r.rows_used == 0:
        return 0.0
    score = 100.0
    score -= 40.0 * r.timestamp_failures / r.rows_total
    score -= 40.0 * r.value_failures / r.rows_total
    score -= 25.0 * (1.0 - r.coverage)
    score -= 20.0 * (1.0 - r.regularity)
    score -= 30.0 * min(1.0, r.negative_values / max(1, r.rows_used))
    score -= 15.0 * min(1.0, r.duplicate_timestamps / max(1, r.rows_used))
    lo, hi = PLAUSIBLE_MEDIAN_W
    if not (lo <= r.median_power_w <= hi):
        score -= 40.0
    if r.days < 7:
        score -= 20.0
    return round(max(0.0, min(100.0, score)), 1)

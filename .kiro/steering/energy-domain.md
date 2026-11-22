---
inclusion: fileMatch
fileMatchPattern: ["backend/src/wattgeist/**/*.py", "backend/tests/**/*.py"]
---

# Energy data rules

These rules exist because each one was a bug in an earlier version or in someone else's tool. Do not relax them.

## Units

- **kW and kWh are different things.** kWh/kW are energy/power. A 30-minute reading of 0.05 kWh is an average of
  100 W. Convert power to energy by multiplying by the interval in hours, never by assuming 1 hour.
- Wh are 1/1000 kWh. A household median above about 15 kW almost always means Wh were read as kWh.
- Money is in currency units (GBP, USD), never pence or cents, inside the backend.

## Time

- The canonical series (`MeterSeries`) is UTC, fixed interval, indexed by **interval start**.
- Timestamps may mark interval **end** (Low Carbon London does). Shift them back by one interval during import.
- Local time is only for analysis that depends on the clock: night windows, tariff windows, calendar days.
- DST: in autumn the 01:00 hour happens twice. Files are often newest-first, so reverse before `ambiguous="infer"`.
  Period-number files (Spanish `Hora` = 1..25) are minutes since local midnight, not clock hours.
- Low Carbon London timestamps are GMT all year. Parse them as UTC and analyse in Europe/London.

## Readings

- Cumulative register readings need differencing. A negative difference is a meter swap or wrap: treat it as missing,
  never as negative consumption.
- Negative interval readings are exported solar. Treat them as missing for consumption analysis.
- When combining 15-minute data into 30-minute buckets, a bucket with any missing part is missing. Partial sums
  understate the night floor and make the vampire look smaller than it is.

## Always-on load

- Daily floor = minimum interval average power for a local day with at least 90% of readings.
- Days with 4 or more zero readings are outages or vacant days: excluded.
- Always-on = median of daily floors over the last 365 days.
- Haunted night = a day whose floor is above its 29-day rolling median by max(3×MAD, 50% of baseline, 80 W).
  Compare against the local baseline so a seasonal rise (winter heating) is not reported as a ghost.

## Bills

- Fill missing intervals with the mean of the same (weekday/weekend, slot) before billing, and use the same filled
  series for every tariff so rankings are fair.
- A time-of-use window with end <= start wraps midnight.

#[[file:docs/methodology.md]]

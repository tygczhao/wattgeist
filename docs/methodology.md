# Methodology

## Always-on load

1. Convert every interval to average power: `W = kWh / interval hours × 1000`.
2. Group by **local** calendar day. Keep a day only if it has at least 90% of its readings and fewer than four zero
   readings (zeros mean an outage, a vacant home or a meter fault, not a 0 W house).
3. The day's floor is its minimum interval power.
4. Always-on load is the **median** daily floor over the last 365 days. Annual always-on energy is `W × 8,760 h`.

NRDC also started from the minimum power seen in smart meter data
([Home Idle Load, 2015](https://www.nrdc.org/sites/default/files/home-idle-load-IP.pdf)). For its Stanford dataset it
reports an idle load of 218 W (the meter minimum) and an always-on load of 164 W, the minimum discounted by 25% to
set aside loads that are idle but not truly always on. WattGeist reports the undiscounted floor, so its number is
comparable to NRDC's 218 W idle-load figure. NRDC's 164 W was about 23% of the annual electricity of the 70,000
Northern California homes it studied.

Half-hour averaging smooths fridge and freezer compressor cycles into a steady draw, so they are part of the floor.
WattGeist lists them as residents rather than vampires.

## Haunted nights

A day is haunted when its floor exceeds the **29-day centred rolling median** of floors by more than

```
max(3 × 1.4826 × MAD, 0.5 × baseline, 80 W)
```

MAD is the median absolute deviation of floors from that rolling baseline. Comparing with a local baseline keeps a
winter-long rise (electric heating) out of the haunted list; it shows in the monthly floor trend instead.
The extra energy of a haunted night is at least `excess W × 24 h`.

## London benchmark

`scripts/build_demo_data.py` runs the production parser and estimator over all 168 partitions of the
[Low Carbon London smart meter dataset](https://data.london.gov.uk/dataset/smartmeter-energy-consumption-data-in-london-households-vqm0d)
(UK Power Networks, CC BY 4.0). Households with at least 300 valid days in their last year are kept.

| Statistic | Value |
|---|---|
| Households | 5,089 |
| Always-on median | 80 W |
| Always-on middle half | 44–138 W |
| Always-on 90th percentile | 224 W |
| Annual use median | 3,111 kWh |
| Always-on share of use, median | 24% |

These homes were measured in 2012–2014. Treat the comparison as a reference point.

## Bills

- The most recent 365 days (or all data if shorter), annualised to 365 days, plus the standing charge.
- Missing intervals are filled with the household's mean for the same weekday/weekend and half-hour slot. Every
  tariff is billed on the same filled series.
- Time-of-use windows use the local clock; windows with `end <= start` wrap midnight.
- Agile (dynamic) prices use a 12 × 2 × 48 matrix: the mean price for each month, weekday/weekend and half hour over
  the year before the snapshot (17,520 half-hourly prices from the Octopus Energy public API).

## Load shifting

On the average day, up to the requested kWh is moved from the dearest slots to the cheapest. A slot can give up at
most its usage above the always-on floor. This is an estimate, not a schedule.

## Import

See `.kiro/specs/meter-import/design.md`. The importer is deterministic. The Kiro Crew `format-reviewer` agent may only propose a parse
configuration, which is parsed and scored like any other and adopted only when it scores higher, or equal after the
heuristic reported an ambiguity.

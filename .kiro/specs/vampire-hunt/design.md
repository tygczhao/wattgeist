# Design Document: Vampire Hunt

## Overview

All logic lives in `analysis/always_on.py`, `analysis/suspects.py` and `analysis/benchmark.py`. These are pure
functions over `MeterSeries`. `service.vampire_report` shapes the response for the API, the MCP server and the
séance tools, so the three surfaces always show the same numbers.

## Why a median of daily minima

- The minimum of a day is the moment when only always-on devices run. Averaging over 30 minutes smooths fridge
  compressor cycles into a steady draw, so the fridge is part of the floor and is listed as a resident.
- The median over a year ignores the occasional night someone left a heater on. Those nights are reported separately.
- NRDC also started from the smart meter minimum. It then discounted that minimum by 25% to get its 164 W
  always-on figure; WattGeist keeps the undiscounted floor, which matches NRDC's 218 W idle-load measure.

## Haunted nights against a local baseline

A fixed threshold against the yearly median flagged every winter day for homes with electric heating. The design
compares each day with a centred 29-day rolling median, so seasonal change shows in the monthly trend instead.

## London benchmark

`scripts/build_demo_data.py` runs the same parser and estimator over all 168 partitions of the Low Carbon London
dataset and keeps households with at least 300 valid days in their last year (5,089 homes). It stores 101
quantiles and a 20 W histogram in `data/benchmark.json`.

| Statistic (5,089 London homes, 2012–2014) | Value |
|---|---|
| Always-on median | 80 W |
| Always-on interquartile range | 44–138 W |
| Annual use median | 3,111 kWh |
| Always-on share median | 24% |

## Correctness Properties

### Property 1: Always-on is bounded

*For any* household series of at least eight days, Always_On SHALL be at least the minimum interval power and at
most the largest daily mean power, and its share of consumption SHALL be within [0, 1].

**Validates: Requirements 1.3, 1.5**

### Property 2: Always-on is shift-equivariant

*For any* household series and any constant extra power P, adding P to every interval SHALL increase Always_On
by P (within rounding).

**Validates: Requirements 1.1, 1.3**

## Testing Strategy

- Unit: known floor, one injected haunted night, a whole-winter rise that must not be haunted, a two-week outage.
- Property: Properties 1–2 in `tests/property/test_properties.py`.

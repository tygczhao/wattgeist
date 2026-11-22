---
description: How to read always-on load, haunted nights and tariff comparisons from WattGeist
always: false
---

# Vampire hunting with WattGeist

## The numbers

- **Always-on load (W)**: the median of each day's lowest half-hour average power over the last year.
  It is what the home draws when nobody is using anything: routers, standby electronics, the fridge's average.
- **Haunted night**: a day whose lowest power stayed well above the 29-day rolling median, by at least
  max(3 × MAD, half the baseline, 80 W). Something stayed on for the whole day and night.
- **Extra energy** of a haunted night is at least `excess W × 24 h`. Multiply by the single-rate price for the cost.

## Reference points

- NRDC (2015), about 70,000 Northern California homes: always-on load averaged 164 W, 23% of electricity use.
  NRDC's 164 W is the meter minimum discounted by 25%; WattGeist's floor is undiscounted (NRDC's idle load, 218 W).
- Low Carbon London (2012–2014), 5,089 homes analysed by WattGeist: median 80 W, middle half 44–138 W.

## Typical standby draws (NRDC Table 3, average per device)

| Device | W |
|---|---|
| Set-top box | 16 |
| TV | 13 |
| Modem | 11 |
| Desktop computer, asleep | 9.5 |
| Wi-Fi router | 5.5 |
| Lights left on 24/7 | 27 |
| Fan left running | 110 |
| Recirculation pump | 70 |

## How to answer

1. `list_households`, then `get_overview` for the household.
2. For a specific night, `get_day_detail` and find when the power was lowest.
3. For money questions, `compare_tariffs` with the flexible kWh per day the user mentions (default 2).

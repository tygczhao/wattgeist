# Design Document: Tariff Simulator

## Overview

`tariffs/models.py` defines `Tariff` (flat, tou, dynamic). `tariffs/engine.py` prices each interval and computes
the bill. `tariffs/shift.py` estimates load-shifting savings on the average day. `scripts/fetch_octopus_tariffs.py`
builds `data/tariffs_uk.json` from the public API.

## Correctness Properties

### Property 1: Bills are linear in price and time-of-use degenerates to flat

*For any* household series, rate r and factor k, the energy cost at k·r SHALL be k times the cost at r, and a
time-of-use tariff whose windows all charge r SHALL cost the same as a flat tariff at r.

**Validates: Requirements 1.1, 1.3**

### Property 2: Time-of-use bills are bounded by their cheapest and dearest rates

*For any* household series and rates cheap < dear, a tariff mixing them SHALL cost between flat-at-cheap and
flat-at-dear.

**Validates: Requirements 1.3**

## Testing Strategy

- Unit: flat arithmetic, midnight-wrapping window, autumn DST hour, presets load, shift caps.
- Property: Properties 1–2.

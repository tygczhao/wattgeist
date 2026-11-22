# Requirements Document

## Introduction

The vampire hunt answers "what does my home burn when nobody is using anything?". NRDC's 2015 study of about
70,000 Northern California homes found always-on load averaged 164 W, about 23% of their electricity. The hunt
measures the household's own floor from meter data, prices it, shows when it spiked, and helps attribute it.

## Glossary

- **Daily_Floor**: the lowest interval-average power (W) of a local calendar day with at least 90% of readings.
- **Always_On**: the median Daily_Floor over the last 365 days.
- **Haunted_Night**: a day whose Daily_Floor is well above its local baseline (29-day rolling median).
- **Suspect_Catalogue**: devices with NRDC-measured average idle watts (`data/suspects.json`).
- **London_Benchmark**: quantiles of Always_On for 5,089 Low Carbon London households computed with the same code.

## Requirements

### Requirement 1: Measure the floor

**User Story:** As a householder, I want one number for my always-on load, so that I know how big the problem is.

#### Acceptance Criteria

1. THE System SHALL compute Daily_Floor in the household's local time zone.
2. IF a day has fewer than 90% of its readings or four or more zero readings, THEN THE System SHALL exclude it.
3. THE System SHALL report Always_On in W, its annual energy (W × 8,760 h) and its share of annual consumption.
4. WHEN fewer than 7 valid days exist, THE System SHALL say so instead of reporting a number.
5. Always_On SHALL lie between the minimum interval power and the largest daily mean power.

### Requirement 2: Price it and compare it

**User Story:** As a householder, I want to know what it costs and whether it is unusual.

#### Acceptance Criteria

1. THE System SHALL price the annual always-on energy at the single-rate tariff in the tariff snapshot and label it an estimate.
2. THE System SHALL place the household's Always_On and annual use as percentiles of the London_Benchmark, naming the sample and its years.

### Requirement 3: Find haunted nights

**User Story:** As a householder, I want to see the nights something was left on, so that I can remember what it was.

#### Acceptance Criteria

1. THE System SHALL flag a day as a Haunted_Night WHEN its Daily_Floor exceeds the 29-day rolling median by more than max(3 × MAD, 50% of the baseline, 80 W).
2. WHEN the floor rises for a whole season, THE System SHALL show it in the monthly floor trend and SHALL NOT flag the season as haunted.
3. FOR each Haunted_Night, THE System SHALL report the excess watts and the minimum extra energy (excess × 24 h).

### Requirement 4: Attribute the floor

**User Story:** As a householder, I want to tick the devices I own and see how much of the floor they explain.

#### Acceptance Criteria

1. THE System SHALL list Suspect_Catalogue devices with their NRDC idle watts and a practical tip.
2. WHEN the user sets device counts, THE System SHALL report explained watts, vampire watts (devices that can be switched off) and unexplained watts (never negative).
3. THE System SHALL mark devices that must stay on (fridge, router, alarm) as residents, not vampires.

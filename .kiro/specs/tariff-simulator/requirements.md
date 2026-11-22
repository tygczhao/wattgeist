# Requirements Document

## Introduction

The tariff simulator bills the household's last 12 months of real usage on real tariffs. The bundled snapshot comes
from the Octopus Energy public API (London region): Flexible (single rate), Go (cheap 00:30–05:30), Cosy (three
cheap windows and a 16:00–19:00 peak) and Agile (half-hourly wholesale-linked prices, summarised as a
12 month × weekday/weekend × 48 slot price matrix from the past year).

## Requirements

### Requirement 1: Bill fairly

**User Story:** As a householder, I want to see what each tariff would have cost me.

#### Acceptance Criteria

1. THE System SHALL bill the most recent 365 days (or all data if shorter) and annualise to 365 days.
2. THE System SHALL fill missing intervals with the household's mean for the same weekday/weekend and slot, and SHALL use the same filled series for every tariff.
3. THE System SHALL apply time-of-use windows by local clock time, including windows that wrap midnight and the repeated DST hour.
4. THE System SHALL include the daily standing charge and rank tariffs from cheapest to dearest.

### Requirement 2: Show the effect of moving load

**User Story:** As a householder, I want to know what moving the dishwasher to the night would save.

#### Acceptance Criteria

1. WHEN the user chooses kWh per day to shift, THE System SHALL move it from the dearest to the cheapest slots of the average day.
2. THE System SHALL NOT move more energy out of a slot than its usage above the always-on floor.
3. FOR a flat tariff, THE System SHALL report zero saving.

### Requirement 3: Custom tariffs

**User Story:** As a householder outside London, I want to enter my own tariff.

#### Acceptance Criteria

1. THE System SHALL accept a flat or time-of-use tariff with windows in HH:MM, rates and a standing charge.
2. IF a tariff is incomplete, THEN THE System SHALL reject it with a message.

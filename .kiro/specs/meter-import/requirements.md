# Requirements Document

## Introduction

Meter import turns whatever file a household can download from its supplier, network operator or meter portal into
one canonical half-hourly (or hourly) energy series. Google PowerMeter and Microsoft Hohm needed a utility partner for
this step. WattGeist has to read the file the user already has, with no column mapping in the common case.

## Glossary

- **Importer**: the pipeline in `backend/src/wattgeist/ingest` (detect, infer, parse, score).
- **Parse_Config**: the declarative description of how to read one file (`ingest/config.py`).
- **Canonical_Series**: `MeterSeries`, UTC, fixed interval, indexed by interval start, kWh per interval.
- **Format_Assistant**: the Kiro Crew `format-reviewer` agent that may propose a different Parse_Config.
- **Quality_Score**: 0–100 score of a parse (`ingest/validate.py`).

## Requirements

### Requirement 1: Read common export formats without configuration

**User Story:** As a householder, I want to drop in the file my supplier gave me, so that I do not have to learn
what "interval end" or "register reading" means.

#### Acceptance Criteria

1. WHEN a CSV, XLSX or Green Button XML file is uploaded, THE Importer SHALL detect the file kind from its content, not only its extension.
2. WHEN a file has account or address lines above the header, THE Importer SHALL locate the header row and skip the preamble.
3. WHEN a file uses semicolons with decimal commas, day-first dates, month-first dates, one row per day with period columns, or a period number of the day, THE Importer SHALL infer the layout and produce a Quality_Score of at least 95 on a regular year of data.
4. THE Importer SHALL preserve total energy: the sum of the Canonical_Series SHALL equal the sum of the readings in the file after unit conversion.
5. THE Canonical_Series SHALL be strictly increasing, unique, fixed-interval, in UTC and indexed by interval start.
6. WHEN 15-minute readings are combined into 30-minute intervals, THE Importer SHALL mark a combined interval missing if any part of it is missing.

### Requirement 2: Respect unit, time and reading conventions

**User Story:** As a householder, I want the numbers to be right, so that I can trust the vampire cost.

#### Acceptance Criteria

1. WHEN values are in W or kW, THE Importer SHALL convert average power to energy using the interval length.
2. WHEN timestamps mark interval end, THE Importer SHALL shift them to interval start.
3. WHEN timestamps carry a UTC offset, THE Importer SHALL use the offset and ignore the configured time zone.
4. WHEN naive timestamps fall in the repeated autumn DST hour, THE Importer SHALL assign both occurrences correctly, including for newest-first files.
5. WHEN readings are cumulative register totals, THE Importer SHALL difference them, and IF a difference is negative THEN THE Importer SHALL treat it as missing and count it as a reset.
6. WHEN a file mixes electricity with gas, or contains exported solar energy, THE Importer SHALL keep only electricity consumption.
7. WHEN a file contains several meters, THE Importer SHALL import the meter with the most readings and list the others.
8. WHEN the column names give no unit or interval marking but the lines above the header do (for example "average watts", "stamped at the end"), THE Importer SHALL use those notes and tell the user it did.
9. WHEN an interval-end time is written as 24:00, THE Importer SHALL read it as midnight at the end of that day.

### Requirement 3: Use AI only as a reviewer

**User Story:** As a privacy-conscious user, I want AI involved only when it helps, so that my data stays with me.

#### Acceptance Criteria

1. WHEN the heuristic parse fails, scores below 90, or reports an ambiguity, THE Importer SHALL ask the Format_Assistant for a Parse_Config, if AI is configured.
2. THE Format_Assistant SHALL receive at most the first 25 non-blank lines and the column names, never the whole file.
3. WHEN the Format_Assistant proposes a Parse_Config, THE Importer SHALL parse with it and SHALL adopt it if its Quality_Score is higher, or equal when the heuristic reported an ambiguity.
4. IF AI is not configured or the Format_Assistant fails, THEN THE Importer SHALL return the heuristic result unchanged.
5. WHEN the heuristic reported no ambiguity and the Format_Assistant's Quality_Score is only equal, THE Importer SHALL keep the heuristic result.

### Requirement 4: Fail safely on hostile or broken files

**User Story:** As the operator of a public demo, I want uploads to be harmless.

#### Acceptance Criteria

1. THE Importer SHALL reject files larger than 60 MB.
2. THE Importer SHALL parse XML with external entities and DTD expansion disabled.
3. IF no timestamps or readings can be identified, THEN THE Importer SHALL return a message the user can act on.

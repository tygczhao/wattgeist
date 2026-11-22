# Implementation Plan: Meter Import

## Tasks

- [x] 1. Canonical series and parse contract
  - [x] 1.1 `MeterSeries` with UTC start-indexed grid, `resample_energy` with whole-bucket rule
    - _Requirements: 1.5, 1.6_
  - [x] 1.2 `ParseConfig` with validation of time zone, delimiter and interval
    - _Requirements: 2.1, 2.2, 2.3_

- [x] 2. Table reading
  - [x] 2.1 Magic-number detection, encodings, header search
    - _Requirements: 1.1, 1.2_
  - [x] 2.2 Delimiter sniffing that does not mistake decimal commas for separators
    - _Requirements: 1.3_

- [x] 3. Deterministic parser
  - [x] 3.1 Long layout with timestamp or date + time columns, DST-safe localisation
    - _Requirements: 2.3, 2.4_
  - [x] 3.2 Wide layout (one row per day)
    - _Requirements: 1.3_
  - [x] 3.3 Period-number layout (Spanish `Hora` 1..25)
    - _Requirements: 1.3, 2.4_
  - [x] 3.4 Cumulative differencing with reset detection
    - _Requirements: 2.5_
  - [x] 3.5 Green Button XML with export and gas filtering
    - _Requirements: 2.6, 4.2_
  - [x]* 3.6 Write property test for energy conservation, for energy and average-power units (kWh, Wh, kW)
    - **Property 1: Energy is conserved by parsing**
    - **Validates: Requirements 1.4, 2.1, 2.2**
  - [x]* 3.7 Write property test for the canonical grid
    - **Property 2: The canonical grid is well formed**
    - **Validates: Requirements 1.5, 2.2, 2.3**
  - [x]* 3.8 Write property test for conservative combining
    - **Property 3: Combining intervals never under-counts**
    - **Validates: Requirements 1.6**

- [x] 4. Inference
  - [x] 4.1 Column roles, units, day/month order resolved by timeline regularity
    - _Requirements: 1.3, 2.1_
  - [x] 4.2 Fuel filter and meter selection
    - _Requirements: 2.6, 2.7_
  - [x] 4.3 Low Carbon London preset (GMT, end-marked)
    - _Requirements: 2.2_
  - [x] 4.4 Row-label channel filter: keep the consumption channel when one column labels each row
        (electricity vs gas, active import vs active export) instead of only a fixed list of column names
    - _Requirements: 2.6_
  - [x] 4.5 Unit read from cell values when no column name states one: a units column first, then the row label
        itself ("Active Import Interval (kW)"), reported to the user in the notes
    - _Requirements: 1.3, 2.1_

- [x] 5. Scoring and AI review
  - [x] 5.1 `ParseReport` and score
    - _Requirements: 3.3_
  - [x] 5.2 Kiro Crew `format-reviewer` agent with 25-line preview and schema-validated JSON reply
    - _Requirements: 3.1, 3.2_
  - [x] 5.5 Agent adapter tests with a fake `kirocrew` (reply adopted on a higher score, failure keeps the heuristic)
    - _Requirements: 3.3, 3.4_
  - [x] 5.3 Pipeline adopts AI config only on a higher score, falls back silently
    - _Requirements: 3.3, 3.4_
  - [x] 5.4 Tie-break: adopt an equal-score AI config only after an ambiguity
    - _Requirements: 3.3, 3.5_
  - [x] 5.5 Preamble hints for unit and interval marking
    - _Requirements: 2.8_

- [x] 6. Format test suite
  - [x] 6.1 Generators for Octopus, LCL, PG&E, wide, register, period-number, Excel, Green Button
    - _Requirements: 1.3_
  - [x] 6.2 Hostile file tests (XXE, garbage)
    - _Requirements: 4.2, 4.3_
  - [x] 6.3 24:00 end-of-day times and preamble-only conventions
    - _Requirements: 2.8, 2.9_
  - [x] 6.4 ESB Networks HDF generator and end-to-end test: average kW stamped at the interval end in Irish local
        time, newest first, with an export channel on the same timestamps. Also the first test of a newest-first
        naive file through the repeated autumn hour
    - _Requirements: 1.3, 2.1, 2.2, 2.4, 2.6_
  - [x] 6.5 File kind detected from content: a CSV named .xlsx or .txt, an XLSX named .csv and a Green Button feed
        named .csv all import correctly (the .xlsx extension no longer overrides readable text)
    - _Requirements: 1.1_
  - [x] 6.6 Multi-meter file: imports the meter with most readings even when another sorts first, and lists all of them
    - _Requirements: 2.7_
  - [x] 6.7 AI reviewer with stub assistants: it receives only the 25-line preview and the column names, a
        strictly higher-scoring proposal is adopted, and a proposal that raises leaves the heuristic result in place
    - _Requirements: 3.2, 3.3, 3.4_
  - [x] 6.8 Upload size limit: the API answers 413 and the service layer raises, with the limit patched small
    - _Requirements: 4.1_
  - [x] 6.9 Conventions the user is shown: timestamps with offsets are unmoved by a wrong household zone, and the
        preamble-derived unit and interval marking appear in the notes
    - _Requirements: 2.3, 2.8_
  - [x] 6.10 Review path when the heuristic parse fails outright: an unparsable file plus a reviewer whose config
        works must adopt the AI result (today only the low-score and ambiguity triggers are tested), and a Green
        Button feed must never be sent for review
    - _Requirements: 3.1_

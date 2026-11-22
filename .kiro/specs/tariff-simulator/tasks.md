# Implementation Plan: Tariff Simulator

## Tasks

- [x] 1. Tariff model and validation
  - _Requirements: 3.1, 3.2_
- [x] 2. Interval pricing for flat, time-of-use and dynamic tariffs
  - _Requirements: 1.3_
- [x] 3. Bill with gap filling, annualisation, standing charge and ranking
  - _Requirements: 1.1, 1.2, 1.4_
- [x]* 3.1 Write property test for linearity and degenerate time-of-use
  - **Property 1: Bills are linear in price and time-of-use degenerates to flat**
  - **Validates: Requirements 1.1, 1.3**
- [x]* 3.2 Write property test for bounds
  - **Property 2: Time-of-use bills are bounded by their cheapest and dearest rates**
  - **Validates: Requirements 1.3**
- [x] 4. Load-shift estimate capped by flexible usage
  - _Requirements: 2.1, 2.2, 2.3_
- [x] 5. Octopus snapshot script (flat, Go, Cosy, Agile price matrix)
  - _Requirements: 1.1_

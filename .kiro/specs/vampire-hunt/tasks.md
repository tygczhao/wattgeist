# Implementation Plan: Vampire Hunt

## Tasks

- [x] 1. Floor estimator
  - [x] 1.1 Valid-day filter (coverage, zero readings) in local time
    - _Requirements: 1.1, 1.2_
  - [x] 1.2 Always-on, annual kWh, share, insufficient-data error
    - _Requirements: 1.3, 1.4_
  - [x]* 1.3 Write property test for bounds
    - **Property 1: Always-on is bounded**
    - **Validates: Requirements 1.3, 1.5**
  - [x]* 1.4 Write property test for shift equivariance
    - **Property 2: Always-on is shift-equivariant**
    - **Validates: Requirements 1.1, 1.3**

- [x] 2. Haunted nights
  - [x] 2.1 Rolling 29-day baseline and MAD threshold
    - _Requirements: 3.1, 3.2_
  - [x] 2.2 Monthly floor trend
    - _Requirements: 3.2_
  - [x] 2.3 Excess watts and minimum extra kWh per night
    - _Requirements: 3.3_

- [x] 3. Benchmark and pricing
  - [x] 3.1 Build London quantiles from all 168 LCL partitions with the production estimator
    - _Requirements: 2.2_
  - [x] 3.2 Price the floor at the snapshot single rate
    - _Requirements: 2.1_

- [x] 4. Suspect catalogue
  - [x] 4.1 NRDC Table 3 idle watts, resident vs vampire, tips
    - _Requirements: 4.1, 4.3_
  - [x] 4.2 Explained / vampire / unexplained watts
    - _Requirements: 4.2_

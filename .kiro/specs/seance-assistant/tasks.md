# Implementation Plan: Séance Assistant

## Tasks

- [x] 1. Read-only MCP tools with trimmed outputs and validated inputs, including monthly usage
  - _Requirements: 1.2, 3.1_
- [x] 2. `seance` Kiro Crew agent: tools first, label estimates, data is not instructions, MCP tools only
  - _Requirements: 1.1, 1.3, 3.2_
- [x] 3. `llm/crew.py`: run the agent through `kirocrew chat`, stream stdout, total timeout, kill on disconnect
  - _Requirements: 2.1, 2.2, 2.3, 3.4_
- [x] 4. NDJSON endpoint and 503 when Kiro Crew is missing
  - _Requirements: 2.1, 3.3_
- [x] 5. Chat panel streams the agent's answer
  - _Requirements: 2.1_
- [x] 6. Tests with a fake `kirocrew`
  - _Requirements: 2.1, 2.2, 2.3, 3.3_

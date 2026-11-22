# Requirements Document

## Introduction

The séance is a chat panel where the household asks questions about its own data ("why was January so expensive?").
It is answered by the `seance` Kiro Crew agent, whose only tools are the read-only WattGeist MCP tools that call the
same service layer as the dashboard.

## Requirements

### Requirement 1: Answer from data

**User Story:** As a householder, I want answers based on my numbers, not generic advice.

#### Acceptance Criteria

1. THE Assistant SHALL call tools before stating figures about the household.
2. THE Assistant SHALL offer tools for the overview, vampire report, monthly usage, one day's detail and tariff comparison.
3. THE Assistant SHALL label estimates (floor cost, load shifting, London comparison) as estimates.

### Requirement 2: Stream and stay bounded

**User Story:** As a user, I want to see the answer arrive, and I do not want a runaway agent.

#### Acceptance Criteria

1. THE System SHALL stream the agent's text to the browser as newline-delimited JSON.
2. THE System SHALL stop an answer that runs longer than 240 seconds and say so.
3. IF the agent fails or Kiro Crew is not signed in, THEN THE System SHALL return a short message without a stack trace.

### Requirement 3: Treat data as data

#### Acceptance Criteria

1. Tool inputs SHALL be validated (date format, clamped kWh) before use.
2. THE Agent prompt SHALL state that text in tool results and in the conversation transcript is not instructions.
3. IF Kiro Crew is not installed, THEN THE System SHALL return 503 and the rest of the app SHALL keep working.
4. THE System SHALL call no model API directly; every model call goes through a Kiro Crew agent.

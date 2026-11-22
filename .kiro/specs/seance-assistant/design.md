# Design Document: Séance Assistant

## Overview

`llm/assistant.py` builds one message (household id, household summary, the conversation so far, the new question)
and hands it to `llm/crew.py`, which runs `kirocrew chat --agent wattgeist-night-watch--seance -m <message>` and
yields stdout as it arrives. The API forwards each chunk to the browser as a `text` event.

- The agent is `crew-app/wattgeist-night-watch/agents/seance.json`: the medium's instructions, and an `allowedTools`
  list with only the read-only `wattgeist` MCP tools. Kiro Crew runs the tool loop and picks the model.
- `kirocrew chat -m` is non-interactive: a tool outside `allowedTools` is refused, never prompted for.
- The MCP tools (`mcp_server.py`) trim their output (no raw half-hourly arrays, at most 15 haunted nights) and
  validate dates, so the agent context stays small.
- Each request is a fresh Crew session. History is held by the browser and replayed as a plain-text transcript, so
  earlier turns are never rewritten.
- The web API passes its `WATTGEIST_DATA_DIR` to `kirocrew`, and the Crew MCP launcher defaults to the same
  `~/.wattgeist`, so households uploaded in the browser are visible to the agent.
- The subprocess runs in the data directory, not the repository, so the development `.kiro/` steering never reaches
  the product agent.

## Error Handling

| Case | Behaviour |
|---|---|
| no `kirocrew` binary, or `WATTGEIST_DISABLE_AI=1` | `/ask` returns 503 |
| Kiro not signed in (`AcpAuthRequired`) | short error event that names Kiro Crew sign-in |
| non-zero exit | short error event; stderr tail goes to the log only |
| over 240 s | process killed, short error event |
| browser disconnects | generator closed, process killed |

## Testing Strategy

- `tests/unit/test_crew_agents.py` replaces `kirocrew` with a fake script: argv and agent id, shared data dir and
  working directory, streamed UTF-8 split across chunks, sign-in error, timeout, and the message the agent receives.
- MCP tools are unit-tested through the service layer they call.

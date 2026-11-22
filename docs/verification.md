# Verification log

Checks run on 5–6 November 2026 against the code in this repository.

## Automated

| Suite | Result |
|---|---|
| Backend unit + property tests (`uv run pytest -q`) | 65 passed |
| Hypothesis properties | 7 properties, 60 examples each |
| Ruff (`E4 E7 E9 F B BLE UP I`) | clean |
| Frontend type check (`tsc -b`) | clean |
| Frontend tests (`vitest`, fast-check) | 4 passed |

## Import accuracy

Eight export formats generated from one truth series (a 2024 year of half-hourly readings) and imported with the
heuristics only, no AI:

| Format | Score | Total energy vs truth |
|---|---|---|
| Octopus CSV (offsets, newest first) | 100 | equal |
| Low Carbon London (GMT, end-marked) | 100 | equal |
| PG&E style (preamble, gas rows, month-first, hourly) | 100 | within 0.03% |
| Wide, one row per day, day-first | 100 | within 0.01% |
| German register totals (`;`, decimal comma, 15 min) | 100 | within 0.02% |
| Spanish period numbers (`Hora` 1–25 across DST) | 100 | equal |
| Excel with preamble, Wh | 100 | equal |
| Green Button XML with a solar export block | 100 | within 0.2% |

## AI import review

A file with columns `col_a, col_b, col_c` and a note above the header ("values are average watts ... stamped at the
END of the half hour"):

- Before preamble hints, the heuristic read Wh with start marks: score 100, energy 2× the truth.
- The AI reviewer proposed W with end marks: score 100, energy equal to the truth. (Measured with the earlier
  direct-API adapter, before the review moved to the Kiro Crew `format-reviewer` agent; re-run pending.)
- The pipeline now adopts an equal-score AI proposal when the heuristic reported an ambiguity, and the heuristic
  reads such notes itself. Both paths are covered by unit tests with a stub assistant.

## Séance

Question to The Haunted Semi: "Why is my always-on load so high, and which nights were haunted?"
(Measured with the earlier direct-API adapter, before the Séance moved to the Kiro Crew `seance` agent; re-run
pending.) The assistant called `get_overview` and `get_vampire_report`, then answered with the 114 W floor, the 67th London
percentile, the winter rise in the monthly floor and the weekend clustering of haunted nights (68 of 86 on
Saturdays or Sundays). Every figure matched the tool output.

## Kiro CLI

- `kiro-cli agent validate` passes for both custom agents.
- `meter-format-detective` added the Irish ESB Networks HDF format (kW, end-marked, import/export channels):
  energy before 1,324.684 kWh (doubled), after 665.397 kWh against a truth of 665.404 kWh.
- `kiro-cli chat --v3 --agent vampire-analyst` connected to the WattGeist MCP server and answered "Which demo
  household has the largest always-on load?" with The Vampire Manor, 574 W, 5,028.2 kWh, £1,337.30 a year,
  98.9th percentile, from `list_households` and `get_overview`.
- The first attempt failed: Kiro's MCP log showed `Failed to connect ... Connection closed`. Running the server by
  hand showed `mcp` 2.x had renamed `FastMCP` to `MCPServer`; the server was migrated and the dependency pinned.

## Kiro Crew app

Installed in a local Kiro Crew 0.12.0 gateway (`kirocrew app install`, trusted alone with `agent.apps_trusted` and
`agent.apps_trusted_local`, then `kirocrew app enable`):

- Registration: 1 agent, 1 skill, the `wattgeist` MCP server and the paused `morning-night-watch` cron.
- `kirocrew cron trigger`: status success in 16,072 ms; the notification listed 86 haunted nights for the demo home
  (the five most recent, then "…and 81 earlier"). A second trigger succeeded in 5,543 ms and posted nothing.
- `kirocrew chat --agent wattgeist-night-watch--night-watch`: the agent answered from the MCP tools with The Vampire
  Manor, 574 W, £1,337.30 a year, 98.9th percentile, worst haunted night 5 March 2013 (+415 W).
- `app.json` also validates with Crew's own `AppManifest` parser.

## Container

`docker build` succeeded; the container served the UI, listed the demo homes and imported an uploaded Spanish CSV.

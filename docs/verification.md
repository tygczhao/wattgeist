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
  direct-API adapter, before the review moved to the Kiro Crew `format-reviewer` agent.)
- The pipeline now adopts an equal-score AI proposal when the heuristic reported an ambiguity, and the heuristic
  reads such notes itself. Both paths are covered by unit tests with a stub assistant.

Through the Kiro Crew `format-reviewer` agent (`POST /api/households`, Kiro Crew 0.12.0, kiro-cli 3.1.0): two
months of the same truth in a file with columns `col_a, col_b, col_c` and no note (`col_a` a meter serial). The
heuristic read `col_a` as Wh; the agent replied in 25 s with `value_column` `col_c` in kWh and `col_a` as the meter
id. Result `parsed_by: ai`, score 100, 439.1 kWh against a truth of 439.073 kWh.

## Séance

Through the Kiro Crew `seance` agent:

- `kirocrew chat --agent wattgeist-night-watch--seance`, The Haunted Semi, "What is my always-on load, and what
  happened on my worst haunted night?": 114 W, 998.6 kWh and about £265.59 a year, 67th London percentile, worst
  night 7 April 2013 at 426 W (+310 W, 7.44 kWh), in 31 s.
- `POST /api/households/<id>/ask` for the household uploaded above, kept in a separate `WATTGEIST_DATA_DIR`:
  84 streamed text events in 39 s. 121.1 W, £282.08 a year, 69th percentile (median 80 W), February 212.3 kWh, all
  equal to the API's own overview and monthly figures. The agent's MCP server saw a household that exists only in
  the web app's data directory, so the directory reaches it through `kirocrew`.
- The first call after `kirocrew app update` answered without tools: the installed app's backend environment was
  still being built (about 20 s) and the MCP connection gave up. The next call worked.

Earlier, with the direct-API adapter: question to The Haunted Semi: "Why is my always-on load so high, and which
nights were haunted?" The assistant called `get_overview` and `get_vampire_report`, then answered with the 114 W floor, the 67th London
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
- v0.2.0 (`kirocrew app update --source ...`): 3 agents and 1 skill registered. `kirocrew cron trigger` succeeded in
  11,222 ms with the data directory now shared at `~/.wattgeist`, and posted the 86-haunted-night notification.

## Container

`docker build` succeeded; the container served the UI, listed the demo homes and imported an uploaded Spanish CSV.

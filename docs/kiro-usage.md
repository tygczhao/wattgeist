# How WattGeist was built with Kiro

WattGeist was built with Kiro: specs first, steering for the domain rules that kept going wrong, hooks to
keep tests and specs honest, two custom agents, an MCP server that Kiro itself uses, property-based tests tied to the
specs, and a Kiro Crew app that runs the product every morning.

## Kiro surfaces

| Surface | What it did for WattGeist |
|---|---|
| Kiro CLI (V3 engine) | Custom agents for new formats and test gaps, hooks, MCP; `kiro-cli agent validate` on every agent change |
| Kiro Crew 0.12 | Hosts the Night Watch app: scheduled check, notification, skill, MCP server, and the agents behind every AI feature (Night Watch chat, the web app's Séance and import review) |

The custom agents ran in the CLI. Crew is where WattGeist runs for a household every morning.

## Spec-driven development

Four specs in `.kiro/specs/`, each `requirements.md` (EARS acceptance criteria) → `design.md` (architecture, correctness
properties, error handling) → `tasks.md` (every task links to requirement numbers).

| Spec | Requirement groups | Correctness properties | Status |
|---|---|---|---|
| meter-import | 4 | 3 | all tasks done |
| vampire-hunt | 4 | 2 | all tasks done |
| tariff-simulator | 3 | 2 | all tasks done |
| seance-assistant | 3 | – | all tasks done |

The spec changed the work in two ways compared with prompting freely:

- **A spec makes gaps visible.** The `Stop` hook asks the agent, at the end of every turn that touched `backend/src`,
  to list requirements that have no test. That list turned into a task list: renamed files (1.1), multi-meter files
  (2.7), the 25-line AI preview limit (3.2), the strictly-better-score branch (3.3), assistant failure (3.4) and the
  60 MB limit (4.1) each got a test, and the test for 1.1 found a real bug (see below).
- **A spec records why.** The tie-break rule for AI proposals (requirement 3.3/3.5, task 5.4) is written down with
  the file that forced it, so the next change cannot quietly undo it.

## Steering

| File | Inclusion | Why it exists |
|---|---|---|
| `product.md` | always | The four features, the voice (Halloween is the costume, not the content), what is out of scope |
| `tech.md` | always | The layering and the one rule that matters most: the AI never writes data, it only proposes a `ParseConfig` |
| `energy-domain.md` | `fileMatch` on backend Python | kW vs kWh, interval start vs end, DST, register differencing, the floor and bill definitions |
| `frontend-design.md` | `fileMatch` on frontend sources | The validated palette, one y-axis per chart, a table view for every chart, number formats |

`energy-domain.md` is the one that paid off most. Every rule in it was a bug first. It includes
`docs/methodology.md` with `#[[file:...]]`, so the agent sees the exact formulas rather than a paraphrase.

## Agent hooks

| Hook | Trigger | Action |
|---|---|---|
| Run the matching tests | `PostFileSave` on `ingest/`, `analysis/`, `tariffs/` | unit + property tests |
| Lint Python | `PostFileSave` on backend Python | `ruff check` |
| Protect generated data | `PreToolUse` on writes | `scripts/guard_generated.py` blocks edits to the benchmark, demo homes and tariff snapshot |
| Check a new meter format | `PostFileSave` on `tests/fixtures.py` | agent prompt: name the format's conventions, add tests for new ones |
| Keep specs and code in sync | `Stop` | agent prompt: tick tasks, add tasks, confirm every property has a test, list untested requirements |

The `Stop` hook did the most work. After the ESB task below it produced the untested-requirements list; after the
follow-up it found that requirements 2.3 and 2.8 were only half covered and closed them.

## Custom agents

### `meter-format-detective`

Adds a new export format test-first. Writes are limited to `backend/src/wattgeist/ingest/**` and `backend/tests/**`;
shell is limited to `pytest` and `ruff`; it loads the energy steering and the import spec as resources.

Two real runs:

1. **Irish ESB Networks HDF export.** Readings in kW, stamped at interval end in Irish local time, newest first, with
   import and export channels in the same column. Before the run the importer scored the file 99.7 but read kW as kWh
   and doubled total energy. The agent wrote a generator, a failing end-to-end test, then generalised the row filter
   (electricity vs gas *and* import vs export) and read the unit from row labels like `Active Import Interval (kW)`.
   After: score 100, total energy 665.397 kWh against a truth of 665.404 kWh. It also extended the energy-conservation
   property to kW readings and added a direct test that both occurrences of the repeated autumn DST hour land on their
   own UTC slot in a newest-first file.
2. **Closing the spec's test gaps.** Twelve tests for the untested requirements. One exposed a real bug: a CSV saved
   with an `.xlsx` name went to the Excel reader and failed. Detection now trusts content over the extension.

The suite grew from 46 to 65 tests across these runs, and every acceptance criterion in the meter-import spec now has a test.

### `vampire-analyst`

Answers questions about a household using only the WattGeist MCP tools. Asked "Which demo household has the largest
always-on load, and how much does it cost per year?", it called `list_households` and `get_overview` and answered:
The Vampire Manor, 574 W, 5,028.2 kWh a year, about £1,337.30 at the single rate, 98.9th percentile of 5,089 London
homes.

## MCP

`backend/src/wattgeist/mcp_server.py` exposes seven read-only tools (`list_households`, `load_meter_file`,
`get_overview`, `get_vampire_report`, `get_day_detail`, `compare_tariffs`, `list_tariffs`). The same service layer
feeds the web UI, the Séance and MCP, so every surface shows the same numbers.

MCP turned Kiro into a user of the product, which is how it found its own bug: the first `vampire-analyst` session
reported the tools as missing, Kiro's MCP log showed `Failed to connect ... Connection closed`, and running the server
by hand showed that `mcp` 2.x had renamed `FastMCP` to `MCPServer`. The server was migrated and the dependency pinned.

## Property-based testing

Seven Hypothesis properties in `backend/tests/property/test_properties.py`, each labelled with the spec property it
checks (energy conservation for kWh, Wh and kW; a well-formed UTC grid; conservative combining; always-on bounds and
shift equivariance; bill linearity and time-of-use bounds). A fast-check suite in `frontend/src/lib/format.test.ts`
checks axis ticks and number formatting for any input.

Properties caught what examples would not: extending conservation to kW readings only passes if the parser multiplies
average power by the interval length for 15-, 30- and 60-minute data alike.

## Kiro Crew

`crew-app/wattgeist-night-watch` is a Crew app, installed and run in a local Kiro Crew 0.12 gateway:

- **`morning-night-watch` script cron**, 07:15 Europe/London, no model call. A manual trigger ran in 16 s and posted
  the haunted-night summary to Crew's notifications; a second trigger posted nothing, because those nights were
  already reported.
- **`night-watch` agent + `vampire-hunting` skill + WattGeist MCP server.** Through `kirocrew chat`, the agent
  answered "which demo home has the largest always-on load, what does it cost, and was its worst haunted night on a
  weekday?" with The Vampire Manor, 574 W, about £1,337.30 a year, worst night Tuesday 5 March 2013 at +415 W.
- **Two Command Bar entries** ("Was last night haunted?", "Which tariff should I be on?") and a notification channel.
- **`seance` and `format-reviewer` agents: the web app's AI.** The API calls no model provider. For the Séance it
  runs `kirocrew chat --agent wattgeist-night-watch--seance -m ...` with the household id and the conversation so
  far, and streams the agent's stdout to the browser; the agent reads the household only through the WattGeist MCP
  tools. For an unsure import it runs the tool-less `format-reviewer` agent with a 25-line preview and the
  `ParseConfig` JSON Schema, validates the JSON reply, and the deterministic parser scores it as before. The web
  app and the Crew MCP server share one data directory (`~/.wattgeist`), so homes uploaded in the browser are
  visible to the agents.

Getting it to run inside Crew surfaced three things the manifest docs do not spell out: `{UV_BIN}` and similar agent
placeholders are only rendered for built-in apps, so the MCP server is declared in the manifest with a Python
launcher; a `command` cron runs in a scratch directory, so the job is a `script` cron that resolves paths from its own
file; and a locally installed app needs both `agent.apps_trusted` and `agent.apps_trusted_local` to be granted alone.

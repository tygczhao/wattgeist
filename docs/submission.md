# Devpost submission

Copy these sections into the Devpost form. Replace the two bracketed links once they exist.

**Category:** Resurrection
**Bonus prizes:** Best Kiro Crew App, Best Demo (automatic)

## Links

- Code: https://github.com/tygczhao/wattgeist
- Live app: [deployment URL]
- Demo video: [YouTube URL, public, under 3 minutes]

## Tagline

The home energy monitor Google and Microsoft switched off in 2011, back from the dead to hunt the vampire load in any
smart meter export.

## Inspiration

In 2009 Google PowerMeter and Microsoft Hohm promised to show every household where its electricity went. Both were
gone by 2012, because neither could get the data without utility partnerships. Fifteen years later most of us can
download our own half-hourly readings, but every supplier exports a different file and nobody reads them. NRDC found
that always-on devices draw about 23% of household electricity in Northern California. We wanted the 2009 idea back,
working from the file you already have.

## What it does

- **Reads any meter export**: CSV, Excel or Green Button XML from the UK, US, Ireland, Germany, Spain and elsewhere.
  It handles preambles, day/month order, decimal commas, one-row-per-day tables, register totals, kW vs kWh,
  interval-end stamps, DST, gas rows and solar export. a Kiro Crew agent reviews only when the automatic reading is unsure, from a
  25-line preview, and its proposal has to score at least as well as the heuristic.
- **Hunts the vampire load**: the always-on floor in watts, its yearly cost, where it sits among 5,089 London homes,
  the floor day by day, and haunted nights (days the floor rose far above its local baseline). A checklist with
  NRDC-measured standby watts shows how much of the floor your devices explain.
- **Re-bills your year** on real Octopus Energy tariffs, including half-hourly Agile prices, and estimates what moving
  flexible load would save.
- **Séance**: ask questions in plain English; a Kiro Crew agent answers from the WattGeist MCP tools.
- **Night Watch** (Kiro Crew app): every morning it pulls your readings and tells you on your phone if last night was
  haunted.

Five real London homes from the Low Carbon London trial ship as demos. One of them, the Haunted Semi, had 86 haunted
nights in a year, 68 of them on a Saturday or Sunday: its median weekend floor was 262 W against 110 W on weekdays.

## How we built it

FastAPI and pandas for the analysis, React with hand-drawn SVG charts, an MCP server, and a Kiro Crew app whose
agents do every AI step: the web app's import review and Séance run as Crew agents through `kirocrew chat`, so
WattGeist calls no model API itself. The analysis code is the same everywhere: the web UI, the Séance, the MCP server
and the Crew job all call one service layer.

## How we used Kiro

See the repository's `docs/kiro-usage.md` for the full write-up. In short:

- **Specs** for all four features, with EARS acceptance criteria, correctness properties and tasks linked to
  requirements. A `Stop` hook lists untested requirements at the end of every turn; closing that list found a real bug
  (renamed CSV files were sent to the Excel reader).
- **Steering**: an always-on product and tech file, plus `fileMatch` steering for energy rules (kW vs kWh, interval
  start vs end, DST) and for the chart design system.
- **Hooks**: tests and lint on save, a `PreToolUse` guard that blocks hand edits to generated data, a fixture-review
  hook, and the spec-sync `Stop` hook.
- **Custom agents**: `meter-format-detective` added Ireland's ESB HDF format test-first (before: 2x the energy; after:
  within 0.001%); `vampire-analyst` answers questions through MCP.
- **MCP**: seven read-only WattGeist tools that Kiro, the Crew agent and any MCP client can call.
- **Property-based testing**: seven Hypothesis properties tied to spec properties, plus fast-check on the frontend.
- **Kiro Crew**: Night Watch is a script cron, three agents, a skill, an MCP server and Command Bar entries, installed
  and run in a Crew gateway. Its `seance` and `format-reviewer` agents are the web app's only AI.

## Challenges

- Meter files lie in quiet ways. A file can be perfectly consistent and still wrong by a factor of two (kW read as
  kWh) or shifted by half an hour (interval end read as start). A quality score cannot see that, so the importer reads
  the notes above the header and lets the AI break ties only when the heuristic admits it is unsure.
- DST. Spain numbers hours 1 to 25 on the autumn change day; London's dataset is GMT all year; newest-first files break
  pandas' DST inference. Each has a test.
- A haunted night is not a cold night. Comparing each day with a 29-day rolling baseline keeps a winter of electric
  heating out of the haunted list.

## What we learned

The always-on floor is the most actionable number in a smart meter file, and almost nobody sees it. Specs plus a hook
that keeps asking "which requirement has no test?" found more bugs than writing tests by feel.

## What's next

More supplier formats through `meter-format-detective`, live Green Button Connect for US utilities, and Night Watch
messages that suggest which device to switch off based on the time the floor was lowest.

## Built with

python, fastapi, pandas, hypothesis, react, typescript, vite, fast-check, mcp, kiro, kiro-crew, docker,
octopus-energy-api, green-button

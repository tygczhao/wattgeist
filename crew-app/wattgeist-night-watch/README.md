# WattGeist Night Watch (Kiro Crew app)

Every morning at 07:15 London time, Night Watch downloads your Octopus Energy half-hourly usage, checks whether
last night was "haunted" (the home never dropped to its usual always-on level), and sends a short message through
Kiro Crew to wherever you talk to your crew: dashboard, Slack, Telegram or Discord.

```
👻 My home: 1 haunted night
• 2026-11-05: never dropped below 412 W (lowest at 03:30), +298 W, about £1.90 extra
Usual always-on load: 114 W. Something stayed on all night; check heaters, fans and chargers.
```

It also adds a **night-watch** agent and two Command Bar entries ("Was last night haunted?", "Which tariff should I
be on?") that answer from the WattGeist MCP server, so every number comes from your meter data.

The app also hosts the two agents behind the WattGeist web app's AI: **seance** (the Séance chat, MCP tools only)
and **format-reviewer** (proposes import settings for an unsure file, no tools). The web API runs them through
`kirocrew chat`, so installing this app and signing in to Kiro is what switches the web app's AI on.

## Install

```bash
./crew-app/build.sh                         # bundles the WattGeist backend into the app folder
kirocrew app install "$(pwd)/crew-app/wattgeist-night-watch"
# trust this one app (the dashboard App Store asks the same thing when you install from there)
kirocrew config set agent.apps_trusted '["wattgeist-night-watch"]'
kirocrew config set agent.apps_trusted_local '["wattgeist-night-watch"]'
kirocrew app enable wattgeist-night-watch
# build the installed app's backend environment once, so the first agent call does not wait ~20 s for it
uv sync --quiet --project ~/.kiro/crew/apps/wattgeist-night-watch/backend
```

To update an installed app after changing it, run `./crew-app/build.sh`, raise `version` in `app.json`, then
`kirocrew app update wattgeist-night-watch --source "$(pwd)/crew-app/wattgeist-night-watch"` with the gateway
running, and the `uv sync` line above again.

The `morning-night-watch` job ships paused. Try it once, then resume it:

```bash
kirocrew cron list                    # find the job id
kirocrew cron trigger <job id>        # runs now; the message appears in Crew's notifications
kirocrew cron resume <job id>         # every morning at 07:15 London time
```

Without credentials the job checks the bundled demo home, so a fresh install shows a message straight away. To
watch your own home, give the gateway `OCTOPUS_API_KEY`, `OCTOPUS_MPAN` and `OCTOPUS_SERIAL` (for example through
`kirocrew secrets`), and the job downloads your readings first.

Ask the agent from the dashboard, Slack, Telegram or Discord, or from a terminal:

```bash
kirocrew chat --agent wattgeist-night-watch--night-watch -m "Was last night haunted?"
```

## What runs where

| Piece | Runs | Model calls |
|---|---|---|
| `morning-night-watch` cron | `bin/night_watch_cron.py` (a Crew script cron) → `wattgeist-nightwatch` | none |
| `night-watch` agent and Command Bar entries | Kiro CLI with the `wattgeist` MCP server | yes |
| `seance` agent | the web API (`kirocrew chat --agent wattgeist-night-watch--seance`), `wattgeist` MCP server | yes |
| `format-reviewer` agent | the web API on an unsure import, no tools, replies with one JSON object | yes |
| `wattgeist` MCP server | `bin/mcp_launcher.py` → `uv run wattgeist-mcp`, data in `~/.wattgeist` (shared with the web app; `WATTGEIST_DATA_DIR` overrides) | none |

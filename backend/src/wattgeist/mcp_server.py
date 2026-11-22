"""WattGeist MCP server: the same usage analysis, offered to Kiro and other MCP clients.

Run: wattgeist-mcp (stdio transport). Optional WATTGEIST_DATA_DIR points at the app's saved households.
All tools are read-only; load_meter_file reads a path on the user's machine, accepts regular files only and limits their size.
"""

from __future__ import annotations

import json
import re
from datetime import date as _date
from pathlib import Path

# mcp 2.x renamed FastMCP to MCPServer (mcp.server.mcpserver); the @tool() decorator and run() work as before
from mcp.server.mcpserver import MCPServer

from . import service
from .analysis import profile
from .tariffs.presets import preset_tariffs

mcp = MCPServer(
    "wattgeist",
    instructions=(
        "Read-only home electricity analysis. Start with list_households, then get_overview for a household id. "
        "Power is in W, energy in kWh, money in the tariff currency."
    ),
)
_booted = False
# Tool arguments come from model output and are untrusted; dates must be strict YYYY-MM-DD before analysis sees them
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _boot() -> None:
    global _booted
    if not _booted:
        service.bootstrap()
        _booted = True


def _home(household_id: str) -> service.Household:
    _boot()
    try:
        return service.STORE.get(household_id)
    except service.NotFound:
        ids = ", ".join(h.id for h in service.STORE.list())
        raise ValueError(f"Unknown household '{household_id}'. Available: {ids}") from None


@mcp.tool()
def list_households() -> str:
    """List demo and saved households with their always-on load (W) and annual use (kWh)."""
    _boot()
    return json.dumps([service.household_card(h) for h in service.STORE.list()])


@mcp.tool()
def load_meter_file(path: str, timezone: str = "Europe/London", name: str = "My home") -> str:
    """Import a smart meter export (CSV, XLSX or Green Button XML) from a local path and return its household id."""
    _boot()
    p = Path(path).expanduser()
    if not p.is_file():
        raise ValueError(f"Not a file: {path}")
    if p.stat().st_size > service.MAX_UPLOAD_BYTES:
        raise ValueError("File is larger than 60 MB")
    h, outcome = service.import_upload(p.read_bytes(), p.name, timezone, name)
    if h is None:
        raise ValueError(outcome.error or "Could not read the file")
    return json.dumps({"household": service.household_card(h), "notes": outcome.notes})


@mcp.tool()
def get_overview(household_id: str) -> str:
    """Coverage, average and annual use, always-on load with yearly cost, and the London comparison."""
    out = service.overview(_home(household_id))
    if out.get("benchmark"):
        out["benchmark"]["always_on"].pop("histogram", None)
    return json.dumps(out, default=str)


@mcp.tool()
def get_vampire_report(household_id: str) -> str:
    """Monthly always-on floor, haunted nights (floor spikes) and the suspect-device breakdown."""
    r = service.vampire_report(_home(household_id))
    r.pop("daily", None)
    r.pop("catalogue", None)
    # At most 15 haunted nights: the Séance agent uses this tool too, and a whole year's list only bloats its context
    r["haunted_nights"] = r["haunted_nights"][:15]
    return json.dumps(r, default=str)


@mcp.tool()
def get_monthly_usage(household_id: str) -> str:
    """Electricity use per calendar month in kWh, with the share of readings present that month."""
    # Added when the Séance moved to a Kiro Crew agent, so the agent keeps every tool the old built-in set had
    return json.dumps(profile.monthly(_home(household_id).series))


@mcp.tool()
def get_day_detail(household_id: str, date: str) -> str:
    """Half-hourly average power (W) for one local date (YYYY-MM-DD)."""
    d = date[:10]
    # Check the format, then that the date exists (fromisoformat rejects 2024-02-30); errors go back as ValueError
    if not _DATE.match(d):
        raise ValueError("date must be YYYY-MM-DD")
    _date.fromisoformat(d)
    return json.dumps(profile.day_detail(_home(household_id).series, d))


@mcp.tool()
def compare_tariffs(household_id: str, kwh_to_shift_per_day: float = 2.0) -> str:
    """Annual cost on each UK tariff in the snapshot, cheapest first, with load-shifting savings."""
    r = service.bills(_home(household_id), max(0.0, min(kwh_to_shift_per_day, 50.0)))
    for b in r["bills"]:
        b.pop("slot_prices", None)
    r.pop("usage_profile", None)
    return json.dumps(r, default=str)


@mcp.tool()
def list_tariffs() -> str:
    """Tariffs in the bundled Octopus Energy snapshot (dynamic tariffs omit their price matrix)."""
    return json.dumps([t.model_dump(exclude={"price_profile"}) for t in preset_tariffs()])


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

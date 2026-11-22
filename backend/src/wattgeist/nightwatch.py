"""Night Watch: checks every day whether last night was haunted, for the Kiro Crew scheduled job and the command line.

It uses exactly the analysis.always_on definition: the local baseline is computed from all history, and only new haunted nights within lookback_days are reported.
A state file records the dates already reported so a night is never announced twice. Output is plain text ready to post in chat,
or structured JSON (--json) for a Crew agent to work with.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from . import service
from .analysis.always_on import InsufficientData, estimate_always_on
from .analysis.profile import day_detail
from .tariffs.presets import preset_tariffs

# Most haunted nights listed in one chat message; a first run can find dozens and nobody reads them all
MAX_LISTED = 5


def _single_rate() -> tuple[float | None, str]:
    flat = next((t for t in preset_tariffs() if t.kind == "flat"), None)
    return (flat.unit_rate, flat.currency) if flat else (None, "GBP")


def check(h: service.Household, seen: set[str], lookback_days: int = 3, today: date | None = None) -> dict:
    """Return {household, always_on_w, new_haunted: [...], message}. seen is the set of dates already reported."""
    ao = estimate_always_on(h.series)
    end = today or h.series.local_energy().index[-1].date()
    window = {(end - timedelta(days=i)).isoformat() for i in range(lookback_days + 1)}
    fresh = [n for n in ao.haunted_nights if n.date in window and n.date not in seen]
    fresh.sort(key=lambda n: n.date)
    price, cur = _single_rate()
    symbol = {"GBP": "£", "USD": "$", "EUR": "€"}.get(cur, "")
    items = []
    for n in fresh:
        d = day_detail(h.series, n.date)
        watts = d.get("watts") or []
        slots = d.get("slots") or []
        # A haunted night means power never fell to its usual floor all day, so report when it was lowest: the best moment to spot the device
        valid = [(w, s) for w, s in zip(watts, slots, strict=False) if w is not None]
        low_w, low_at = min(valid) if valid else (None, None)
        items.append({**n.__dict__, "cost": round(n.extra_kwh * price, 2) if price else None, "lowest_at": low_at})
    shown = items[-MAX_LISTED:]
    if items:
        lines = [f"👻 {h.name}: {len(items)} haunted night{'s' if len(items) > 1 else ''}"]
        for it in shown:
            cost = f", about {symbol}{it['cost']:.2f} extra" if it["cost"] is not None else ""
            at = f" (lowest at {it['lowest_at']})" if it["lowest_at"] else ""
            lines.append(f"• {it['date']}: never dropped below {it['floor_w']:.0f} W{at}, +{it['excess_w']:.0f} W{cost}")
        if len(items) > len(shown):
            lines.append(f"…and {len(items) - len(shown)} earlier.")
        lines.append(f"Usual always-on load: {ao.watts:.0f} W. Something stayed on all night; check heaters, fans and chargers.")
        message = "\n".join(lines)
    else:
        message = f"🕯️ {h.name}: a quiet night. Always-on load {ao.watts:.0f} W."
    return {"household": h.id, "always_on_w": ao.watts, "new_haunted": items, "message": message}


def _state_path() -> Path:
    return service.data_dir() / "nightwatch-seen.json"


def _load_seen() -> dict[str, list[str]]:
    p = _state_path()
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except (OSError, json.JSONDecodeError):
        return {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="wattgeist-nightwatch", description="Report new haunted nights.")
    ap.add_argument("--household", default=os.environ.get("WATTGEIST_HOUSEHOLD", ""), help="household id")
    ap.add_argument("--refresh-octopus", action="store_true",
                    help="re-download readings with OCTOPUS_API_KEY / OCTOPUS_MPAN / OCTOPUS_SERIAL first")
    ap.add_argument("--lookback", type=int, default=3)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    service.bootstrap()
    if args.refresh_octopus:
        from .ingest.octopus import OctopusError, fetch_consumption_csv

        try:
            csv = fetch_consumption_csv(
                os.environ.get("OCTOPUS_API_KEY", ""), os.environ.get("OCTOPUS_MPAN", ""),
                os.environ.get("OCTOPUS_SERIAL", ""),
            )
        except OctopusError as exc:
            print(f"Night Watch could not reach Octopus: {exc}", file=sys.stderr)
            return 2
        name = os.environ.get("WATTGEIST_HOME_NAME", "My home")
        hid = args.household or "octopus-home"
        h, outcome = service.import_upload(csv, "octopus.csv", "Europe/London", name)
        if h is None:
            print(f"Night Watch could not read the Octopus data: {outcome.error}", file=sys.stderr)
            return 2
        # Save under a fixed id: Night Watch refreshes the same home every day instead of creating a new one
        if h.id != hid:
            service.STORE.delete(h.id)
            h.id = hid
            service.STORE.put(h)
        args.household = hid

    if not args.household:
        print("Choose a household with --household (see `wattgeist-nightwatch --household haunted-semi`).",
              file=sys.stderr)
        return 2
    try:
        h = service.STORE.get(args.household)
    except service.NotFound:
        ids = ", ".join(x.id for x in service.STORE.list())
        print(f"Unknown household '{args.household}'. Known: {ids}", file=sys.stderr)
        return 2

    seen_all = _load_seen()
    seen = set(seen_all.get(h.id, []))
    try:
        result = check(h, seen, lookback_days=args.lookback)
    except InsufficientData as exc:
        print(f"Night Watch needs more data: {exc}", file=sys.stderr)
        return 2
    seen_all[h.id] = sorted(seen | {n["date"] for n in result["new_haunted"]})[-400:]
    _state_path().write_text(json.dumps(seen_all))
    print(json.dumps(result) if args.json else result["message"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

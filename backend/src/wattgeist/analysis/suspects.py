"""Suspect devices: NRDC's 2015 measured average idle watts per device split the measured always-on load into known suspects and unidentified ghosts.

kind=resident marks devices that must stay powered (fridge, router, alarm) and only get efficiency tips; kind=vampire is standby you can eliminate.
fridge_freezer is not an NRDC measurement but an estimate from typical energy-label consumption (estimate=true); the UI must say so.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources


@lru_cache(maxsize=1)
def catalogue() -> dict:
    return json.loads(resources.files("wattgeist.data").joinpath("suspects.json").read_text(encoding="utf-8"))


def explain_floor(always_on_w: float, owned: dict[str, int]) -> dict:
    """owned: device id -> count. Returns the known total, the unexplained remainder and the items sorted by watts.

    A negative remainder means the ticked devices exceed the measured floor (some are switched off or more efficient than NRDC's sample), so it is clamped to 0.
    """
    devices = {d["id"]: d for d in catalogue()["devices"]}
    items = []
    for dev_id, qty in owned.items():
        d = devices.get(dev_id)
        if d is None or qty <= 0:
            continue
        items.append({**d, "quantity": int(qty), "total_w": round(d["watts"] * qty, 1)})
    items.sort(key=lambda x: x["total_w"], reverse=True)
    known = round(sum(i["total_w"] for i in items), 1)
    vampire_w = round(sum(i["total_w"] for i in items if i["kind"] == "vampire"), 1)
    return {
        "always_on_w": always_on_w,
        "explained_w": known,
        "vampire_w": vampire_w,
        "unexplained_w": round(max(0.0, always_on_w - known), 1),
        "items": items,
    }

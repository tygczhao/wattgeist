"""Bundled UK tariff snapshot (fetched from the Octopus Energy public API by scripts/fetch_octopus_tariffs.py)."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources

from .models import Tariff


@lru_cache(maxsize=1)
def snapshot() -> dict:
    f = resources.files("wattgeist.data").joinpath("tariffs_uk.json")
    if not f.is_file():
        return {"tariffs": [], "fetched_at": None, "source": ""}
    return json.loads(f.read_text(encoding="utf-8"))


def preset_tariffs() -> list[Tariff]:
    return [Tariff.model_validate(t) for t in snapshot()["tariffs"]]


def preset_by_id(tariff_id: str) -> Tariff | None:
    return next((t for t in preset_tariffs() if t.id == tariff_id), None)

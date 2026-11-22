"""Comparison with Low Carbon London households.

The distribution is computed offline by scripts/build_demo_data.py with exactly the same analysis code as the app and stored as quantiles.
These homes are London homes from 2011–2014, so for other places and years the comparison is only a reference point; the UI names the sample.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources

import numpy as np


@lru_cache(maxsize=1)
def distribution() -> dict | None:
    f = resources.files("wattgeist.data").joinpath("benchmark.json")
    if not f.is_file():
        return None
    return json.loads(f.read_text(encoding="utf-8"))


def percentile_of(value: float, quantiles: list[float]) -> float:
    """quantiles[i] is the i-th percentile (101 points). Linear interpolation gives value's percentile within the sample."""
    q = np.asarray(quantiles, dtype=float)
    ranks = np.linspace(0, 100, len(q))
    return float(np.clip(np.interp(value, q, ranks), 0, 100))


def compare(always_on_w: float, annual_kwh: float | None) -> dict | None:
    dist = distribution()
    if dist is None:
        return None
    ao = dist["always_on_w"]["quantiles"]
    out = {
        "population": dist["households"],
        "source": dist["source"],
        "always_on": {
            "percentile": round(percentile_of(always_on_w, ao), 1),
            "median_w": round(ao[50], 1),
            "p25_w": round(ao[25], 1),
            "p75_w": round(ao[75], 1),
            "histogram": dist["always_on_w"]["histogram"],
        },
    }
    if annual_kwh is not None:
        ak = dist["annual_kwh"]["quantiles"]
        out["annual"] = {"percentile": round(percentile_of(annual_kwh, ak), 1), "median_kwh": round(ak[50], 0)}
    return out

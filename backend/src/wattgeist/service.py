"""Application service layer: a household is one imported canonical series plus derived analysis.

The API, the MCP server and the Q&A assistant all call this layer, so all three show exactly the same numbers.
Households live in memory and are persisted by id under WATTGEIST_DATA_DIR (default ~/.wattgeist) as gzip CSV and JSON,
so they survive restarts; demo households are re-imported from the bundled Low Carbon London subset at every start.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import re
import secrets
import threading
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from importlib import resources
from pathlib import Path

import pandas as pd

from .analysis import profile
from .analysis.always_on import AlwaysOnResult, InsufficientData, estimate_always_on
from .analysis.benchmark import compare
from .analysis.suspects import catalogue, explain_floor
from .ingest.config import ParseConfig
from .ingest.pipeline import ImportOutcome, import_meter_file
from .series import MeterSeries
from .tariffs.engine import compute_bill, slot_prices
from .tariffs.models import Tariff
from .tariffs.presets import preset_tariffs, snapshot
from .tariffs.shift import shift_savings

log = logging.getLogger(__name__)
_ID = re.compile(r"^[a-z0-9-]{3,64}$")
MAX_UPLOAD_BYTES = 60 * 1024 * 1024


class NotFound(KeyError):
    pass


@dataclass
class Household:
    id: str
    name: str
    series: MeterSeries
    demo: bool = False
    tagline: str = ""
    source: dict = field(default_factory=dict)
    owned_devices: dict[str, int] = field(default_factory=dict)
    custom_tariffs: list[Tariff] = field(default_factory=list)
    _always_on: AlwaysOnResult | None = field(default=None, repr=False)

    def always_on(self) -> AlwaysOnResult:
        if self._always_on is None:
            self._always_on = estimate_always_on(self.series)
        return self._always_on


def data_dir() -> Path:
    p = Path(os.environ.get("WATTGEIST_DATA_DIR", Path.home() / ".wattgeist"))
    p.mkdir(parents=True, exist_ok=True)
    return p


class Store:
    """Thread-safe household store; FastAPI runs sync routes in a thread pool, hence the lock."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._homes: dict[str, Household] = {}

    def put(self, h: Household, persist: bool = True) -> None:
        with self._lock:
            self._homes[h.id] = h
        if persist and not h.demo:
            _save(h)

    def get(self, hid: str) -> Household:
        with self._lock:
            h = self._homes.get(hid)
        if h is None:
            raise NotFound(hid)
        return h

    def list(self) -> list[Household]:
        with self._lock:
            return sorted(self._homes.values(), key=lambda h: (not h.demo, h.name))

    def delete(self, hid: str) -> None:
        with self._lock:
            h = self._homes.pop(hid, None)
        if h is None:
            raise NotFound(hid)
        if not h.demo:
            (data_dir() / f"{hid}.csv.gz").unlink(missing_ok=True)
            (data_dir() / f"household-{hid}.json").unlink(missing_ok=True)


def _save(h: Household) -> None:
    d = data_dir()
    # Persist as gzip CSV: a year of half-hourly data is about 17,000 rows and a few hundred KB compressed, not worth adding pyarrow
    h.series.energy_kwh.rename("kwh").to_frame().to_csv(d / f"{h.id}.csv.gz", index_label="ts", compression="gzip")
    meta = {
        "id": h.id, "name": h.name, "timezone": h.series.timezone, "interval_minutes": h.series.interval_minutes,
        "meter_id": h.series.meter_id, "source": h.source, "owned_devices": h.owned_devices,
        "custom_tariffs": [t.model_dump() for t in h.custom_tariffs],
    }
    (d / f"household-{h.id}.json").write_text(json.dumps(meta, default=str))


def _load_saved(store: Store) -> None:
    # Only read household metadata files; the same directory holds other JSON such as Night Watch state
    for meta_file in data_dir().glob("household-*.json"):
        try:
            meta = json.loads(meta_file.read_text())
            if not _ID.match(meta["id"]):
                continue
            df = pd.read_csv(data_dir() / f"{meta['id']}.csv.gz", compression="gzip")
            energy = pd.Series(df["kwh"].to_numpy(dtype=float), index=pd.to_datetime(df["ts"], utc=True))
            s = MeterSeries(
                energy_kwh=energy.asfreq(f"{meta['interval_minutes']}min"),
                interval_minutes=int(meta["interval_minutes"]),
                timezone=meta["timezone"],
                meter_id=meta.get("meter_id"),
                label=meta["name"],
            )
            store.put(
                Household(
                    id=meta["id"], name=meta["name"], series=s, source=meta.get("source", {}),
                    owned_devices=meta.get("owned_devices", {}),
                    custom_tariffs=[Tariff.model_validate(t) for t in meta.get("custom_tariffs", [])],
                ),
                persist=False,
            )
        except Exception as exc:  # noqa: BLE001  one corrupt file must not stop the service starting, but it must be logged
            log.warning("skipping unreadable saved household %s: %s", meta_file.name, exc)
            continue


@lru_cache(maxsize=1)
def demo_index() -> list[dict]:
    f = resources.files("wattgeist.data").joinpath("demo/index.json")
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else []


def load_demos(store: Store) -> None:
    for d in demo_index():
        raw = gzip.decompress(resources.files("wattgeist.data").joinpath(f"demo/{d['id']}.csv.gz").read_bytes())
        outcome = import_meter_file(raw, f"{d['id']}.csv", "Europe/London", analysis_timezone="Europe/London")
        if outcome.result is None:
            continue
        store.put(
            Household(
                id=d["id"], name=d["name"], series=outcome.result.series, demo=True, tagline=d["tagline"],
                source={
                    "kind": "demo",
                    "dataset": "Low Carbon London (UK Power Networks), CC BY 4.0",
                    "household": d["lclid"],
                    "report": asdict(outcome.result.report),
                    "notes": outcome.notes,
                },
            ),
            persist=False,
        )


STORE = Store()


def bootstrap() -> None:
    load_demos(STORE)
    _load_saved(STORE)


def new_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "home"
    return f"{slug}-{secrets.token_hex(3)}"


def import_upload(
    data: bytes,
    filename: str | None,
    timezone: str,
    name: str,
    *,
    config: ParseConfig | None = None,
    assistant=None,
) -> tuple[Household | None, ImportOutcome]:
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("The file is larger than 60 MB.")
    outcome = import_meter_file(
        data, filename, timezone, analysis_timezone=timezone, config_override=config, assistant=assistant
    )
    if outcome.result is None:
        return None, outcome
    h = Household(
        id=new_id(name),
        name=name.strip()[:80] or "My home",
        series=outcome.result.series,
        source={
            "kind": "upload",
            "filename": (filename or "")[:200],
            "config": outcome.result.config.model_dump(),
            "report": asdict(outcome.result.report),
            "notes": outcome.notes,
            "ai_notes": outcome.ai_notes,
            "parsed_by": outcome.source,
            "meter_ids": outcome.result.meter_ids[:50],
        },
    )
    STORE.put(h)
    return h, outcome


# ---------- Response assembly (shared by API, MCP and the assistant) ----------


def household_card(h: Household) -> dict:
    out = {"id": h.id, "name": h.name, "demo": h.demo, "tagline": h.tagline, "timezone": h.series.timezone}
    try:
        ao = h.always_on()
        out.update(always_on_w=ao.watts, annual_kwh=ao.annual_consumption_kwh, share=ao.share_of_consumption)
    except InsufficientData as exc:
        out["error"] = str(exc)
    return out


def overview(h: Household) -> dict:
    s = profile.summary(h.series)
    out: dict = {"household": household_card(h), "summary": s, "source": h.source}
    try:
        ao = h.always_on()
    except InsufficientData as exc:
        out["always_on"] = None
        out["always_on_error"] = str(exc)
        return out
    cheapest_flat = next((t for t in preset_tariffs() if t.kind == "flat"), None)
    price = cheapest_flat.unit_rate if cheapest_flat else None
    out["always_on"] = {
        "watts": ao.watts,
        "annual_kwh": ao.annual_kwh,
        "share": ao.share_of_consumption,
        "annual_cost": round(ao.annual_kwh * price, 2) if price else None,
        "price_used": price,
        "currency": cheapest_flat.currency if cheapest_flat else None,
        "days_used": ao.days_used,
        "days_excluded": ao.days_excluded,
        "haunted_nights": len(ao.haunted_nights),
    }
    out["benchmark"] = compare(ao.watts, ao.annual_consumption_kwh)
    return out


def vampire_report(h: Household) -> dict:
    ao = h.always_on()
    floors = ao.daily_floor_w
    base = ao.baseline_w
    return {
        "watts": ao.watts,
        "annual_kwh": ao.annual_kwh,
        "share": ao.share_of_consumption,
        "daily": [
            {"date": str(d), "floor_w": round(float(w), 1), "baseline_w": round(float(base[d]), 1)}
            for d, w in floors.items()
        ],
        "monthly": [{"month": str(m), "floor_w": round(float(w), 1)} for m, w in ao.monthly_floor_w.items()],
        "haunted_nights": [asdict(n) for n in ao.haunted_nights[:60]],
        "suspects": explain_floor(ao.watts, h.owned_devices),
        "catalogue": catalogue(),
    }


def all_tariffs(h: Household) -> list[Tariff]:
    return preset_tariffs() + list(h.custom_tariffs)


def bills(h: Household, kwh_to_shift: float = 2.0) -> dict:
    try:
        floor = h.always_on().watts
    except InsufficientData:
        floor = 0.0
    out = []
    for t in all_tariffs(h):
        b = asdict(compute_bill(h.series, t))
        b["kind"] = t.kind
        b["notes"] = t.notes
        b["slot_prices"] = slot_prices(t)
        b["shift"] = shift_savings(h.series, t, kwh_to_shift, floor) if t.kind != "flat" else None
        out.append(b)
    out.sort(key=lambda b: b["annual_cost"])
    cheapest = out[0]["annual_cost"] if out else 0
    for b in out:
        b["vs_cheapest"] = round(b["annual_cost"] - cheapest, 2)
    snap = snapshot()
    return {
        "bills": out,
        "usage_profile": profile.average_day(h.series),
        "snapshot": {"fetched_at": snap.get("fetched_at"), "source": snap.get("source"), "region": snap.get("region")},
        "kwh_to_shift": kwh_to_shift,
    }


def set_devices(h: Household, owned: dict[str, int]) -> dict:
    known = {d["id"] for d in catalogue()["devices"]}
    h.owned_devices = {k: max(0, min(50, int(v))) for k, v in owned.items() if k in known and int(v) > 0}
    STORE.put(h)
    return explain_floor(h.always_on().watts, h.owned_devices)


def add_tariff(h: Household, t: Tariff) -> Tariff:
    t.validate_complete()
    t = t.model_copy(update={"id": f"custom-{secrets.token_hex(3)}"})
    h.custom_tariffs.append(t)
    STORE.put(h)
    return t

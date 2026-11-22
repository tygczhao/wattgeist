"""Green Button (NAESB ESPI) XML parsing.

Green Button is the "Download my data" standard that most US utilities offer.
The file is an Atom feed: UsagePoint -> MeterReading -> ReadingType (unit, multiplier, accumulation)
and IntervalBlock (interval readings), linked by href. The links are rebuilt here, keeping only electricity readings in the delivered (consumption) direction.
XML is parsed with defusedxml to block external entity (XXE) and entity-expansion attacks, since the file is a user upload.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
from defusedxml import ElementTree as SafeET

from .table import ImportError_

ATOM = "{http://www.w3.org/2005/Atom}"
ESPI = "{http://naesb.org/espi}"

# ESPI unit codes: 72 = Wh (energy), 38 = W (power). Gas units (therms etc.) are not handled
UOM_WH = 72
UOM_W = 38
# accumulationBehaviour: 4 = deltaData (interval deltas, the usual case); 1/3/9 are cumulative register readings that need differencing
CUMULATIVE_BEHAVIOURS = {1, 3, 9}
# flowDirection: 19 = reverse (energy sent to the grid, e.g. solar export), which is not household consumption
FLOW_REVERSE = 19
# ServiceCategory kind: 0 = electricity; 1 = gas, 2 = water, ...
SERVICE_ELECTRICITY = 0


@dataclass
class _ReadingType:
    uom: int = UOM_WH
    power_of_ten: int = 0
    accumulation: int = 4
    flow: int = 1


@dataclass
class GreenButtonData:
    points: pd.DataFrame  # columns: ts (UTC interval start), kwh, duration_s
    tz_offset_seconds: int | None = None
    notes: list[str] = field(default_factory=list)


def _int(el, tag: str, default: int) -> int:
    child = el.find(f"{ESPI}{tag}") if el is not None else None
    try:
        return int(child.text) if child is not None and child.text else default
    except ValueError:
        return default


def _links(entry) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for link in entry.findall(f"{ATOM}link"):
        out.setdefault(link.get("rel", ""), []).append((link.get("href") or "").rstrip("/"))
    return out


def parse_green_button(data: bytes) -> GreenButtonData:
    """Parse an ESPI XML feed into interval energy points. Timestamps are UTC epoch seconds, so DST never applies."""
    try:
        root = SafeET.fromstring(data)
    except Exception as exc:  # defusedxml raises several exception types; turn them all into a readable error
        raise ImportError_(f"Could not read the XML file: {exc}") from exc

    entries = root.findall(f"{ATOM}entry") if root.tag == f"{ATOM}feed" else [root]
    reading_types: dict[str, _ReadingType] = {}
    meter_reading_rt: dict[str, str] = {}  # MeterReading self href → ReadingType href
    usage_point_kind: dict[str, int] = {}
    blocks: list[tuple[str, object]] = []  # (owning MeterReading href, IntervalBlock element)
    tz_offset: int | None = None

    for entry in entries:
        content = entry.find(f"{ATOM}content")
        if content is None:
            continue
        links = _links(entry)
        self_href = (links.get("self") or [""])[0]
        for child in content:
            tag = child.tag.replace(ESPI, "")
            if tag == "ReadingType":
                reading_types[self_href] = _ReadingType(
                    uom=_int(child, "uom", UOM_WH),
                    power_of_ten=_int(child, "powerOfTenMultiplier", 0),
                    accumulation=_int(child, "accumulationBehaviour", 4),
                    flow=_int(child, "flowDirection", 1),
                )
            elif tag == "MeterReading":
                rt = [h for h in links.get("related", []) if "ReadingType" in h]
                if rt:
                    meter_reading_rt[self_href] = rt[0]
            elif tag == "UsagePoint":
                sc = child.find(f"{ESPI}ServiceCategory")
                usage_point_kind[self_href] = _int(sc, "kind", SERVICE_ELECTRICITY)
            elif tag == "IntervalBlock":
                up = (links.get("up") or [self_href.rsplit("/", 1)[0]])[0]
                # "up" looks like .../MeterReading/1/IntervalBlock; dropping the last segment gives the MeterReading self href
                owner = up[: -len("/IntervalBlock")] if up.endswith("/IntervalBlock") else up
                blocks.append((owner, child))
            elif tag == "LocalTimeParameters":
                tz_offset = _int(child, "tzOffset", 0)

    if not blocks:
        raise ImportError_("No IntervalBlock elements were found in this Green Button file.")

    notes: list[str] = []
    rows: list[tuple[int, int, float]] = []
    single_rt = next(iter(reading_types.values())) if len(reading_types) == 1 else None
    skipped_export = skipped_other = 0

    for owner, block in blocks:
        rt = reading_types.get(meter_reading_rt.get(owner, ""), single_rt) or _ReadingType()
        usage_point = owner.split("/MeterReading")[0]
        if usage_point_kind.get(usage_point, SERVICE_ELECTRICITY) != SERVICE_ELECTRICITY:
            skipped_other += 1
            continue
        if rt.flow == FLOW_REVERSE:
            skipped_export += 1
            continue
        if rt.uom not in (UOM_WH, UOM_W):
            skipped_other += 1
            continue
        for reading in block.findall(f"{ESPI}IntervalReading"):
            period = reading.find(f"{ESPI}timePeriod")
            value_el = reading.find(f"{ESPI}value")
            if period is None or value_el is None or value_el.text is None:
                continue
            start = _int(period, "start", -1)
            duration = _int(period, "duration", 0)
            if start < 0 or duration <= 0:
                continue
            raw = float(value_el.text) * (10.0**rt.power_of_ten)
            # Wh -> kWh; W is average power over the interval, so multiply by its length in hours to get Wh
            kwh = raw / 1000.0 if rt.uom == UOM_WH else raw * duration / 3600.0 / 1000.0
            rows.append((start, duration, kwh))
        if rt.accumulation in CUMULATIVE_BEHAVIOURS:
            notes.append("cumulative")

    if skipped_export:
        notes.append(f"Ignored {skipped_export} block(s) of exported energy (e.g. solar).")
    if skipped_other:
        notes.append(f"Ignored {skipped_other} block(s) that are not electricity usage.")
    if not rows:
        raise ImportError_("This Green Button file has no electricity usage readings.")

    df = pd.DataFrame(rows, columns=["start", "duration_s", "kwh"])
    df["ts"] = pd.to_datetime(df["start"], unit="s", utc=True)
    return GreenButtonData(points=df[["ts", "kwh", "duration_s"]], tz_offset_seconds=tz_offset, notes=notes)

"""Download half-hourly consumption from the Octopus Energy account API (UK smart meters).

Authentication: HTTP Basic with the API key as the username and an empty password (as used by the open-source Home Assistant integration).
Endpoint: /v1/electricity-meter-points/{mpan}/meters/{serial}/consumption/, returning interval_start / interval_end / consumption (kWh),
paged through the "next" field. The data is turned into CSV text and goes through the normal import pipeline, exactly like an uploaded file.
The API key is only read from the environment or a call argument and is never written to a file or a log.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import httpx

BASE = "https://api.octopus.energy/v1"
_MPAN = re.compile(r"^\d{13}$")
_SERIAL = re.compile(r"^[A-Za-z0-9]{4,20}$")


class OctopusError(RuntimeError):
    pass


def fetch_consumption_csv(
    api_key: str, mpan: str, serial: str, days: int = 400, client: httpx.Client | None = None
) -> bytes:
    """Download the last days of half-hourly consumption and return CSV bytes with the same columns as the Octopus website export."""
    if not _MPAN.match(mpan):
        raise OctopusError("MPAN must be 13 digits.")
    if not _SERIAL.match(serial):
        raise OctopusError("Meter serial looks wrong (letters and digits only).")
    if not api_key:
        raise OctopusError("An Octopus API key is required.")
    since = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    url: str | None = f"{BASE}/electricity-meter-points/{mpan}/meters/{serial}/consumption/"
    params: dict | None = {"period_from": since, "page_size": 25000, "order_by": "period"}
    own = client is None
    c = client or httpx.Client(timeout=30.0, headers={"User-Agent": "wattgeist"})
    rows: list[str] = [" Consumption (kWh), Start, End"]
    try:
        while url:
            r = c.get(url, params=params, auth=(api_key, ""))
            if r.status_code == 401:
                raise OctopusError("Octopus rejected the API key.")
            if r.status_code == 404:
                raise OctopusError("Octopus does not know this MPAN and serial number.")
            r.raise_for_status()
            data = r.json()
            for item in data.get("results", []):
                rows.append(f"{float(item['consumption'])},{item['interval_start']},{item['interval_end']}")
            # "next" is a complete URL that already carries the paging parameters, so later requests send no params
            url, params = data.get("next"), None
    finally:
        if own:
            c.close()
    if len(rows) == 1:
        raise OctopusError("Octopus returned no readings for this meter in the period.")
    return ("\n".join(rows) + "\n").encode()

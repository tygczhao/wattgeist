"""Night Watch and Octopus download: same definition as the analysis layer, no repeated reports, API paging and authentication."""

from __future__ import annotations

import json

import httpx
import pandas as pd
import pytest

from tests import fixtures as fx
from wattgeist import nightwatch, service
from wattgeist.ingest.octopus import OctopusError, fetch_consumption_csv
from wattgeist.ingest.pipeline import import_meter_file
from wattgeist.series import MeterSeries


def _home(t: pd.Series) -> service.Household:
    s = MeterSeries(energy_kwh=t.tz_convert("UTC").asfreq("30min"), interval_minutes=30, timezone="Europe/London")
    return service.Household(id="t", name="Test", series=s)


def test_reports_only_recent_new_haunted_nights():
    t = fx.truth_series(start="2024-01-01", end="2024-03-31 23:30", floor_w=100).copy()
    for day in ("2024-02-10", "2024-03-30"):
        start = pd.Timestamp(day, tz="Europe/London")
        mask = (t.index >= start) & (t.index < start + pd.Timedelta(days=1))
        t[mask] += 0.15  # 300 W more that day
    h = _home(t)
    first = nightwatch.check(h, seen=set(), lookback_days=3)
    assert [n["date"] for n in first["new_haunted"]] == ["2024-03-30"]
    assert "300 W" in first["message"] or "+3" in first["message"]
    again = nightwatch.check(h, seen={"2024-03-30"}, lookback_days=3)
    assert again["new_haunted"] == []
    assert "quiet night" in again["message"]


def test_message_lists_at_most_five_nights():
    t = fx.truth_series(start="2024-01-01", end="2024-03-31 23:30", floor_w=100).copy()
    for i in range(8):
        start = pd.Timestamp("2024-03-01", tz="Europe/London") + pd.Timedelta(days=3 * i)
        mask = (t.index >= start) & (t.index < start + pd.Timedelta(days=1))
        t[mask] += 0.15
    out = nightwatch.check(_home(t), seen=set(), lookback_days=60)
    assert len(out["new_haunted"]) == 8
    assert out["message"].count("•") == 5
    assert "3 earlier" in out["message"]


def _octopus_transport(pages: dict[str, dict], expect_key: str):
    def handler(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("authorization", "")
        import base64

        user = base64.b64decode(auth.split()[-1]).decode().split(":")[0] if auth else ""
        if user != expect_key:
            return httpx.Response(401, json={"detail": "Authentication credentials were not provided."})
        key = "page2" if "page=2" in str(request.url) else "page1"
        return httpx.Response(200, json=pages[key])

    return httpx.MockTransport(handler)


def test_octopus_fetch_paginates_and_imports():
    t = fx.truth_series(start="2024-06-01", end="2024-06-20 23:30")
    rows = [{"consumption": round(v, 5), "interval_start": ts.isoformat(), "interval_end": (ts + pd.Timedelta(minutes=30)).isoformat()}
            for ts, v in t.items()]
    half = len(rows) // 2
    base = "https://api.octopus.energy/v1/electricity-meter-points/1234567890123/meters/21L1234567/consumption/"
    pages = {"page1": {"count": len(rows), "next": base + "?page=2", "results": rows[:half]},
             "page2": {"count": len(rows), "next": None, "results": rows[half:]}}
    client = httpx.Client(transport=_octopus_transport(pages, "sk_live_test"))
    csv = fetch_consumption_csv("sk_live_test", "1234567890123", "21L1234567", client=client)
    o = import_meter_file(csv, "octopus.csv", "Europe/London")
    assert o.error is None
    assert o.result.series.energy_kwh.sum() == pytest.approx(t.sum(), rel=1e-6)


def test_octopus_bad_key_and_bad_mpan():
    client = httpx.Client(transport=_octopus_transport({}, "right"))
    with pytest.raises(OctopusError, match="rejected"):
        fetch_consumption_csv("wrong", "1234567890123", "21L1234567", client=client)
    with pytest.raises(OctopusError, match="13 digits"):
        fetch_consumption_csv("k", "123", "21L1234567", client=client)
    with pytest.raises(OctopusError, match="serial"):
        fetch_consumption_csv("k", "1234567890123", "../../etc", client=client)


def test_saved_households_ignore_other_json(tmp_path, monkeypatch):
    monkeypatch.setenv("WATTGEIST_DATA_DIR", str(tmp_path))
    (tmp_path / "nightwatch-seen.json").write_text(json.dumps({"x": ["2024-01-01"]}))
    store = service.Store()
    t = fx.truth_series(start="2024-01-01", end="2024-01-20 23:30")
    h = _home(t)
    h.id = "saved-home"
    store.put(h)
    fresh = service.Store()
    service._load_saved(fresh)
    assert [x.id for x in fresh.list()] == ["saved-home"]
    assert fresh.get("saved-home").series.energy_kwh.sum() == pytest.approx(t.sum(), rel=1e-9)

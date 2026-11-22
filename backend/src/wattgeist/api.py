"""HTTP API (FastAPI). Serves the built frontend from WATTGEIST_STATIC_DIR when present, so one process is a full deployment.

Uploads are untrusted input: size-limited, parsed but never executed; XML goes through defusedxml.
Error messages are returned to users verbatim, so ImportError_ messages are written as plain English a user can act on.
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from . import __version__, service
from .analysis import profile
from .analysis.always_on import InsufficientData
from .ingest.config import ParseConfig
from .ingest.infer import infer_config
from .ingest.table import ImportError_, detect_file_kind, raw_preview
from .llm.crew import llm_available
from .tariffs.models import Tariff

log = logging.getLogger("wattgeist")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    service.bootstrap()
    yield


app = FastAPI(title="WattGeist", version=__version__, lifespan=lifespan)


def _home(hid: str) -> service.Household:
    try:
        return service.STORE.get(hid)
    except service.NotFound:
        raise HTTPException(404, "Household not found") from None


def _check_tz(tz: str) -> str:
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(422, f"Unknown time zone: {tz}") from None
    return tz


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "version": __version__, "ai": llm_available(), "households": len(service.STORE.list())}


@app.get("/api/households")
def list_households() -> list[dict]:
    return [service.household_card(h) for h in service.STORE.list()]


async def _read_upload(file: UploadFile) -> bytes:
    data = await file.read(service.MAX_UPLOAD_BYTES + 1)
    if len(data) > service.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "The file is larger than 60 MB.")
    if not data:
        raise HTTPException(422, "The file is empty.")
    return data


@app.post("/api/import/preview")
async def import_preview(file: UploadFile = File(...), timezone: str = Form("Europe/London")) -> dict:
    """Infer without saving: return the raw-line preview and the inferred settings so the user can check columns and units."""
    data = await _read_upload(file)
    _check_tz(timezone)
    try:
        kind = detect_file_kind(data, file.filename)
        inf = infer_config(data, file.filename, timezone)
    except ImportError_ as exc:
        raise HTTPException(422, str(exc)) from None
    return {
        "preview": raw_preview(data, kind),
        "columns": inf.columns,
        "config": inf.config.model_dump(),
        "notes": inf.notes,
        "ambiguities": inf.ambiguities,
        "meter_ids": inf.meter_ids[:50],
    }


@app.post("/api/households")
async def create_household(
    file: UploadFile = File(...),
    name: str = Form("My home"),
    timezone: str = Form("Europe/London"),
    config: str | None = Form(None),
    use_ai: bool = Form(True),
) -> dict:
    data = await _read_upload(file)
    _check_tz(timezone)
    cfg = None
    if config:
        try:
            cfg = ParseConfig.model_validate(json.loads(config))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise HTTPException(422, f"Invalid import settings: {exc}") from None
    assistant = None
    if use_ai and cfg is None and llm_available():
        # 导入复核由 Kiro Crew 的 format-reviewer agent 完成；仅在用户未手动指定设置且本机可用 kirocrew 时启用
        from .llm.parse_assist import CrewFormatAssistant

        assistant = CrewFormatAssistant()
    try:
        h, outcome = service.import_upload(data, file.filename, timezone, name, config=cfg, assistant=assistant)
    except (ImportError_, ValueError) as exc:
        raise HTTPException(422, str(exc)) from None
    if h is None:
        raise HTTPException(422, outcome.error or "The file could not be read.")
    return {"household": service.household_card(h), "source": h.source}


@app.delete("/api/households/{hid}")
def delete_household(hid: str) -> dict:
    h = _home(hid)
    if h.demo:
        raise HTTPException(403, "Demo households cannot be deleted.")
    service.STORE.delete(hid)
    return {"deleted": hid}


@app.get("/api/households/{hid}/overview")
def get_overview(hid: str) -> dict:
    return service.overview(_home(hid))


@app.get("/api/households/{hid}/vampires")
def get_vampires(hid: str) -> dict:
    try:
        return service.vampire_report(_home(hid))
    except InsufficientData as exc:
        raise HTTPException(422, str(exc)) from None


class DevicesIn(BaseModel):
    devices: dict[str, int] = Field(default_factory=dict)


@app.put("/api/households/{hid}/devices")
def put_devices(hid: str, body: DevicesIn) -> dict:
    try:
        return service.set_devices(_home(hid), body.devices)
    except InsufficientData as exc:
        raise HTTPException(422, str(exc)) from None


@app.get("/api/households/{hid}/heatmap")
def get_heatmap(hid: str, days: int = 365) -> dict:
    return profile.heatmap(_home(hid).series, days=max(7, min(days, 1500)))


@app.get("/api/households/{hid}/monthly")
def get_monthly(hid: str) -> list[dict]:
    return profile.monthly(_home(hid).series)


@app.get("/api/households/{hid}/day/{day}")
def get_day(hid: str, day: str) -> dict:
    return profile.day_detail(_home(hid).series, day[:10])


@app.get("/api/households/{hid}/bills")
def get_bills(hid: str, shift_kwh: float = 2.0) -> dict:
    return service.bills(_home(hid), max(0.0, min(shift_kwh, 50.0)))


@app.post("/api/households/{hid}/tariffs")
def post_tariff(hid: str, tariff: Tariff) -> dict:
    try:
        return service.add_tariff(_home(hid), tariff).model_dump()
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    history: list[dict] = Field(default_factory=list)


@app.post("/api/households/{hid}/ask")
def post_ask(hid: str, body: AskIn) -> StreamingResponse:
    """Stream assistant events as NDJSON; the frontend parses one line at a time."""
    h = _home(hid)
    if not llm_available():
        # 503 文案指向 Kiro Crew：Séance 只能由 wattgeist-night-watch app 的 seance agent 回答，没有其他模型后端
        raise HTTPException(503, "AI is not configured on this server (install Kiro Crew and the WattGeist app).")
    from .llm.assistant import ask

    def gen():
        for ev in ask(h, body.question, body.history):
            if ev.get("type") != "noop":
                yield json.dumps(ev) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


# ---------- Frontend static files ----------
_static = Path(os.environ.get("WATTGEIST_STATIC_DIR", Path(__file__).resolve().parents[3] / "frontend" / "dist"))
if _static.is_dir():
    app.mount("/assets", StaticFiles(directory=_static / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        target = (_static / path).resolve()
        if path and target.is_file() and target.is_relative_to(_static.resolve()):
            return FileResponse(target)
        return FileResponse(_static / "index.html")


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        "wattgeist.api:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
    )

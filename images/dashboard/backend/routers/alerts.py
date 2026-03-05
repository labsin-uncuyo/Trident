"""Alert endpoints — read & stream SLIPS IDS alerts."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.models import AlertEntry
from backend.services.file_tailer import read_ndjson_file, tail_ndjson

logger = logging.getLogger("dashboard.alerts")

router = APIRouter(prefix="/api/alerts", tags=["alerts"])

OUTPUTS_DIR = Path("/outputs")


def _current_run_id() -> str | None:
    p = OUTPUTS_DIR / ".current_run"
    if p.exists():
        return p.read_text().strip()
    return None


def _alerts_path(run_id: str | None = None) -> Path:
    rid = run_id or _current_run_id()
    if not rid:
        return OUTPUTS_DIR / "__nonexistent__"
    return OUTPUTS_DIR / rid / "slips" / "defender_alerts.ndjson"


@router.get("")
async def get_alerts(run_id: str | None = None, limit: int = 500):
    """Read alerts for the current (or specified) run."""
    path = _alerts_path(run_id)
    entries = read_ndjson_file(path, max_lines=limit)
    return {"run_id": run_id or _current_run_id(), "count": len(entries), "alerts": entries}


@router.websocket("/ws")
async def ws_alerts(ws: WebSocket):
    """Live-stream new alerts as they are appended."""
    await ws.accept()
    run_id = _current_run_id()
    path = _alerts_path(run_id)

    try:
        async for entry in tail_ndjson(path, from_beginning=False, poll_interval=1.0):
            await ws.send_json({"type": "alert", "run_id": run_id, "data": entry})
    except (WebSocketDisconnect, Exception):
        pass

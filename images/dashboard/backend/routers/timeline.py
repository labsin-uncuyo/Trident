"""Agent timeline REST + WebSocket endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.services.file_tailer import read_ndjson_file, tail_ndjson

logger = logging.getLogger("dashboard.timeline")

router = APIRouter(prefix="/api/timeline", tags=["timeline"])

OUTPUTS_DIR = Path("/outputs")

# Mapping of agent name → relative path(s) within a run directory
_TIMELINE_PATHS: dict[str, list[str]] = {
    "coder56": [
        "coder56/auto_responder_timeline.jsonl",
    ],
    "db_admin": [
        "benign_agent/db_admin_timeline.jsonl",
    ],
    "soc_god_server": [
        "defender/server/auto_responder_timeline.jsonl",
    ],
    "soc_god_compromised": [
        "defender/compromised/auto_responder_timeline.jsonl",
    ],
}


def _current_run_id() -> str | None:
    p = OUTPUTS_DIR / ".current_run"
    if p.exists():
        return p.read_text().strip()
    return None


def _find_timeline_path(agent: str, run_id: str | None = None) -> Path | None:
    rid = run_id or _current_run_id()
    if not rid:
        return None
    paths = _TIMELINE_PATHS.get(agent, [])
    for rel in paths:
        p = OUTPUTS_DIR / rid / rel
        if p.exists():
            return p
    # Try generic pattern
    if paths:
        return OUTPUTS_DIR / rid / paths[0]  # the expected path (tailer will wait)
    return None


@router.get("/agents")
async def list_agents():
    """List known agent names."""
    return {"agents": list(_TIMELINE_PATHS.keys())}


@router.get("/{agent}")
async def get_timeline(agent: str, run_id: str | None = None, limit: int = 500):
    """Read timeline entries for an agent."""
    path = _find_timeline_path(agent, run_id)
    if path is None:
        return {"agent": agent, "count": 0, "entries": []}
    entries = read_ndjson_file(path, max_lines=limit)
    return {"agent": agent, "count": len(entries), "entries": entries}


@router.websocket("/{agent}/ws")
async def ws_timeline(ws: WebSocket, agent: str):
    """Live-stream timeline entries for an agent."""
    await ws.accept()
    run_id = _current_run_id()
    path = _find_timeline_path(agent, run_id)

    if path is None:
        await ws.send_json({"type": "error", "msg": f"No timeline path for agent '{agent}'"})
        await ws.close()
        return

    try:
        async for entry in tail_ndjson(path, from_beginning=False, poll_interval=1.0):
            await ws.send_json({"type": "timeline", "agent": agent, "data": entry})
    except (WebSocketDisconnect, Exception):
        pass

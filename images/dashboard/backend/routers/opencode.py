"""File-backed OpenCode routes + WebSocket merged stream."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.services.opencode_client import get_session_messages, load_all_agent_states

logger = logging.getLogger("dashboard.opencode_router")

router = APIRouter(prefix="/api/opencode", tags=["opencode"])


# ── REST endpoints ──────────────────────────────────────────────────

@router.get("/hosts")
async def get_hosts_compat():
    """Compatibility endpoint; returns per-agent file source state."""
    return (await get_agents())


@router.get("/agents")
async def get_agents(run_id: str | None = None):
    state = load_all_agent_states(run_id=run_id)
    return {"run_id": state.get("run_id"), "updated_at": state.get("updated_at", ""), "agents": state.get("agents", {})}


@router.get("/state")
async def get_state(run_id: str | None = None):
    return load_all_agent_states(run_id=run_id)


@router.get("/sessions")
async def list_sessions(run_id: str | None = None):
    return load_all_agent_states(run_id=run_id).get("sessions", {})


@router.get("/sessions/{session_id}/messages")
async def get_session_messages_endpoint(session_id: str, run_id: str | None = None):
    return get_session_messages(session_id=session_id, run_id=run_id)


# ── WebSocket: live session stream ──────────────────────────────────

@router.websocket("/ws")
async def ws_opencode(ws: WebSocket):
    """Stream merged OpenCode state from mounted output files."""
    await ws.accept()
    prev_signature = ""

    try:
        while True:
            try:
                state = load_all_agent_states()
            except Exception:
                await asyncio.sleep(2)
                continue

            signature = (
                f"{state.get('run_id','')}|{state.get('updated_at','')}|"
                f"{len(state.get('sessions', {}))}|{len(state.get('messages_by_session', {}))}"
            )
            if signature != prev_signature:
                await ws.send_json({"type": "state", "data": state})
                prev_signature = signature

            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("ws_opencode ended: %s", exc)

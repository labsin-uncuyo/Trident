"""OpenCode proxy routes + WebSocket live session stream."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from backend.services.opencode_client import HOSTS, get_client

logger = logging.getLogger("dashboard.opencode_router")

router = APIRouter(prefix="/api/opencode", tags=["opencode"])


def _validate_host(host: str) -> None:
    if host not in HOSTS:
        raise HTTPException(404, f"Unknown host '{host}'. Valid: {list(HOSTS)}")


# ── REST endpoints ──────────────────────────────────────────────────

@router.get("/hosts")
async def get_hosts():
    """List configured OpenCode hosts."""
    results = {}
    for name, url in HOSTS.items():
        client = get_client(name)
        health = await client.health()
        results[name] = {"url": url, "healthy": health.get("healthy", False)}
    return results


@router.get("/{host}/health")
async def host_health(host: str):
    _validate_host(host)
    return await get_client(host).health()


@router.get("/{host}/sessions")
async def list_sessions(host: str):
    """List all sessions on a host with their status."""
    _validate_host(host)
    return await get_client(host).list_sessions()


@router.get("/{host}/sessions/{session_id}/messages")
async def get_session_messages(host: str, session_id: str):
    """Fetch all messages for a session."""
    _validate_host(host)
    return await get_client(host).get_messages(session_id)


# ── WebSocket: live session stream ──────────────────────────────────

@router.websocket("/{host}/ws")
async def ws_opencode(ws: WebSocket, host: str):
    """Stream OpenCode session updates for a host.

    Polls the OpenCode HTTP API every 1s and pushes full state each
    time something changes.  The frontend simply replaces its local
    state with whatever arrives — no delta / append logic needed.
    """
    if host not in HOSTS:
        await ws.close(code=4004, reason=f"Unknown host: {host}")
        return

    await ws.accept()
    client = get_client(host)
    prev_sessions: dict[str, str] = {}
    prev_msg_counts: dict[str, int] = {}

    try:
        while True:
            try:
                sessions = await client.list_sessions()
            except Exception:
                await asyncio.sleep(2)
                continue

            # Push session map whenever it changes
            if sessions != prev_sessions:
                await ws.send_json({
                    "type": "sessions",
                    "host": host,
                    "data": sessions,
                })
                prev_sessions = dict(sessions)

            # For each active session, push FULL message list when count changes
            for sid, status in sessions.items():
                if status not in ("idle", "busy", "running"):
                    continue
                try:
                    msgs = await client.get_messages(sid)
                except Exception:
                    continue
                msg_count = len(msgs)
                if msg_count != prev_msg_counts.get(sid, 0):
                    await ws.send_json({
                        "type": "messages",
                        "host": host,
                        "session_id": sid,
                        "data": msgs,       # full list, not delta
                        "total": msg_count,
                        "full": True,
                    })
                    prev_msg_counts[sid] = msg_count

            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("ws_opencode(%s) ended: %s", host, exc)

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

    Polls /session/status every 2s, diffs against previous state,
    and pushes new/changed sessions and their latest messages.
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
            sessions = await client.list_sessions()

            # Detect new / status-changed sessions
            changed_ids: list[str] = []
            for sid, status in sessions.items():
                if sid not in prev_sessions or prev_sessions[sid] != status:
                    changed_ids.append(sid)

            # Send session list if anything changed
            if sessions != prev_sessions:
                await ws.send_json({
                    "type": "sessions",
                    "host": host,
                    "data": sessions,
                })

            # For each active/changed session, fetch messages and push new ones
            for sid in sessions:
                if sessions[sid] in ("idle", "busy", "running") or sid in changed_ids:
                    msgs = await client.get_messages(sid)
                    msg_count = len(msgs)
                    if msg_count != prev_msg_counts.get(sid, 0):
                        # Send only new messages (delta)
                        old_count = prev_msg_counts.get(sid, 0)
                        new_msgs = msgs[old_count:] if old_count < msg_count else msgs
                        await ws.send_json({
                            "type": "messages",
                            "host": host,
                            "session_id": sid,
                            "data": new_msgs,
                            "total": msg_count,
                        })
                        prev_msg_counts[sid] = msg_count

            prev_sessions = dict(sessions)
            await asyncio.sleep(2)
    except (WebSocketDisconnect, Exception):
        pass

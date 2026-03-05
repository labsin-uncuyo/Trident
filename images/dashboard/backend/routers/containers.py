"""Container status REST + WebSocket endpoints."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.models import ContainerInfo
from backend.services.docker_client import list_containers

router = APIRouter(prefix="/api/containers", tags=["containers"])


@router.get("", response_model=list[ContainerInfo])
async def get_containers():
    """Return status of all lab_* containers."""
    return list_containers()


@router.websocket("/ws")
async def ws_containers(ws: WebSocket):
    """Stream container status changes every 3 seconds."""
    await ws.accept()
    prev_snapshot: str = ""
    try:
        while True:
            containers = list_containers()
            snapshot = json.dumps(
                [c.model_dump() for c in containers], sort_keys=True
            )
            if snapshot != prev_snapshot:
                await ws.send_json(
                    {"type": "containers", "data": [c.model_dump() for c in containers]}
                )
                prev_snapshot = snapshot
            await asyncio.sleep(3)
    except (WebSocketDisconnect, Exception):
        pass

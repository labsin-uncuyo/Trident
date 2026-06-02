"""Replay router with WebSocket for playback control."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Body

from backend.services.replay_client import load_replay, get_events_in_range, list_available_runs

logger = logging.getLogger("dashboard.replay")

router = APIRouter(prefix="/api/replay", tags=["replay"])

# Store active replay sessions
# replay_id -> { replay_data, clients: set[WebSocket] }
_active_replays: dict[str, dict[str, Any]] = {}


@router.get("/runs")
async def list_runs():
    """List all available run directories for replay."""
    runs = await list_available_runs()
    return {"runs": runs}


@router.post("/load")
async def load_replay_endpoint(
    path: str | None = Body(default=None),
    run_id: str | None = Body(default=None),
):
    """Load a replay from path or run_id.

    Args:
        path: Direct path to run directory (e.g., "/outputs/run_20250102_123456")
        run_id: Run ID (loaded from /outputs/{run_id})

    Returns:
        Replay metadata with timeline info
    """
    if not path and not run_id:
        raise HTTPException(400, "Either 'path' or 'run_id' must be provided")

    result = await load_replay(run_id=run_id, path_override=path)
    if "error" in result:
        raise HTTPException(400, result["error"])

    replay_id = result["run_id"]

    # Store replay data for WebSocket access
    _active_replays[replay_id] = {
        "replay_data": result,
        "clients": set(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    # Return metadata without full events list (for initial load)
    # Don't send initial_events - let WebSocket stream them during playback
    # This prevents showing stale events from the beginning when replay starts
    return {
        "replay_id": replay_id,
        "path": result["path"],
        "start_time_ms": result["start_time_ms"],
        "end_time_ms": result["end_time_ms"],
        "duration_ms": result["duration_ms"],
        "event_count": result["event_count"],
    }


@router.get("/{replay_id}/events")
async def get_events(
    replay_id: str,
    start_ms: int | None = None,
    end_ms: int | None = None,
):
    """Get events within a time range.

    Args:
        replay_id: The run/replay ID
        start_ms: Start time in milliseconds (defaults to replay start)
        end_ms: End time in milliseconds (defaults to replay end)
    """
    if replay_id not in _active_replays:
        # Try to load it
        result = await load_replay(run_id=replay_id)
        if "error" in result:
            raise HTTPException(404, f"Replay not found: {replay_id}")
        _active_replays[replay_id] = {
            "replay_data": result,
            "clients": set(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    replay_data = _active_replays[replay_id]["replay_data"]

    if start_ms is None:
        start_ms = replay_data["start_time_ms"]
    if end_ms is None:
        end_ms = replay_data["end_time_ms"]

    all_events = replay_data["events"]
    filtered = [
        e for e in all_events
        if start_ms <= e.get("timestamp_ms", 0) <= end_ms
    ]

    return {
        "replay_id": replay_id,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "count": len(filtered),
        "events": filtered,
    }


@router.websocket("/{replay_id}/ws")
async def replay_websocket(ws: WebSocket, replay_id: str):
    """WebSocket for replay playback control.

    Client messages:
        {"type": "play", "speed": 1.0} - Start/resume playback
        {"type": "pause"} - Pause playback
        {"type": "seek", "position_ms": 123456} - Seek to position
        {"type": "set_speed", "speed": 2.0} - Change playback speed

    Server messages:
        {"type": "state", "position_ms": 123456, "playing": true, "speed": 1.0}
        {"type": "events", "events": [...]}
        {"type": "error", "message": "..."}
    """
    await ws.accept()

    # Load replay data asynchronously
    if replay_id not in _active_replays:
        logger.debug("Replay %s: Loading data from disk (async)...", replay_id)
        result = await load_replay(run_id=replay_id)
        if "error" in result:
            await ws.send_json({"type": "error", "message": result["error"]})
            await ws.close()
            return
        _active_replays[replay_id] = {
            "replay_data": result,
            "clients": set(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        logger.debug("Replay %s: Loaded %d events", replay_id, result.get("event_count", 0))
    else:
        logger.debug("Replay %s: Using cached data", replay_id)

    replay_data = _active_replays[replay_id]["replay_data"]
    all_events = replay_data["events"]
    start_time = replay_data["start_time_ms"]
    end_time = replay_data["end_time_ms"]

    # Register client
    _active_replays[replay_id]["clients"].add(ws)

    # Playback state
    current_pos = start_time
    speed = 1.0
    playing = False
    last_event_index = -1
    has_sent_initial_batch = False  # Track if we've sent the first batch of events

    # Send initial state - don't send events yet, wait for play command
    # This prevents showing stale events at the start
    await ws.send_json({
        "type": "state",
        "replay_id": replay_id,
        "position_ms": current_pos,
        "playing": playing,
        "speed": speed,
        "duration_ms": replay_data["duration_ms"],
        "start_time_ms": start_time,
        "end_time_ms": end_time,
    })

    update_interval = 0.1  # 10Hz update rate
    last_update_time = asyncio.get_event_loop().time()

    try:
        while True:
            # Wait for client message with timeout
            try:
                msg_raw = await asyncio.wait_for(ws.receive_json(), timeout=update_interval)
            except asyncio.TimeoutError:
                msg_raw = None

            # Process client message
            if msg_raw:
                msg_type = msg_raw.get("type")

                if msg_type == "play":
                    playing = True
                    speed = float(msg_raw.get("speed", speed))
                    logger.debug("Replay %s: playing at %sx speed", replay_id, speed)

                    # Send initial events when play is first clicked (if not already sent)
                    if not has_sent_initial_batch:
                        # Send events up to current position + a small window
                        events_window = [
                            e for e in all_events
                            if e.get("timestamp_ms", 0) <= current_pos + 10000  # 10 second window
                        ]
                        if events_window:
                            await ws.send_json({
                                "type": "events",
                                "replay_id": replay_id,
                                "events": events_window,
                            })
                            last_event_index = len(events_window) - 1
                        has_sent_initial_batch = True

                elif msg_type == "pause":
                    playing = False
                    logger.debug("Replay %s: paused", replay_id)

                elif msg_type == "seek":
                    new_pos = int(msg_raw.get("position_ms", current_pos))
                    current_pos = max(start_time, min(end_time, new_pos))
                    # Reset event index on seek
                    last_event_index = -1
                    # Send events at new position (all events up to this point)
                    events_at_pos = [
                        e for e in all_events
                        if e.get("timestamp_ms", 0) <= current_pos
                    ]
                    await ws.send_json({
                        "type": "events",
                        "replay_id": replay_id,
                        "events": events_at_pos,
                    })
                    last_event_index = len(events_at_pos) - 1
                    logger.debug("Replay %s: seeked to %d, sent %d events", replay_id, current_pos, len(events_at_pos))

                elif msg_type == "set_speed":
                    speed = float(msg_raw.get("speed", 1.0))
                    logger.debug("Replay %s: speed set to %sx", replay_id, speed)

            # Update playback
            now = asyncio.get_event_loop().time()
            elapsed_real = (now - last_update_time) * 1000  # ms
            last_update_time = now

            if playing and speed > 0:
                # Advance position based on speed
                elapsed_replay = elapsed_real * speed
                old_pos = current_pos
                current_pos += elapsed_replay

                # Clamp to end
                if current_pos >= end_time:
                    current_pos = end_time
                    playing = False
                    await ws.send_json({"type": "playback_complete", "replay_id": replay_id})

                # Find events that occurred in this time window
                new_events = []
                for i, event in enumerate(all_events):
                    if i <= last_event_index:
                        continue
                    event_ts = event.get("timestamp_ms", 0)
                    if old_pos < event_ts <= current_pos:
                        new_events.append(event)
                        last_event_index = i
                    elif event_ts > current_pos:
                        break

                # Send state update
                await ws.send_json({
                    "type": "state",
                    "replay_id": replay_id,
                    "position_ms": current_pos,
                    "playing": playing,
                    "speed": speed,
                    "duration_ms": replay_data["duration_ms"],
                })

                # Send new events if any
                if new_events:
                    await ws.send_json({
                        "type": "events",
                        "replay_id": replay_id,
                        "events": new_events,
                    })

    except WebSocketDisconnect:
        logger.debug("Replay %s: WebSocket disconnected", replay_id)
    except Exception as exc:
        logger.debug("Replay %s: WebSocket error: %s", replay_id, exc)
        await ws.send_json({"type": "error", "replay_id": replay_id, "message": str(exc)})
    finally:
        # Unregister client
        _active_replays[replay_id]["clients"].discard(ws)
        # Clean up if no clients
        if not _active_replays[replay_id]["clients"]:
            # Keep replay data cached for a while, could add TTL later
            pass

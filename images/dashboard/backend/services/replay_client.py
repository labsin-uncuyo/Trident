"""Replay service for loading and streaming historical logs."""

from __future__ import annotations

import asyncio
import json
import os
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.services.file_tailer import read_ndjson_file

OUTPUTS_DIR = Path(os.getenv("OUTPUTS_DIR", "/outputs"))
logger = logging.getLogger("dashboard.replay")

# Timeline file paths within a run directory
_TIMELINE_PATHS = [
    "coder56/auto_responder_timeline.jsonl",
    "benign_agent/db_admin_timeline.jsonl",
    "benign_agent/opencode_api_messages.json",
    "defender/server/auto_responder_timeline.jsonl",
    "defender/compromised/auto_responder_timeline.jsonl",
    "defender/server/opencode_api_messages.json",
    "defender/compromised/opencode_api_messages.json",
]

_ALERTS_PATH = "slips/defender_alerts.ndjson"


def _parse_iso_timestamp(ts: str | None | int | float) -> int:
    """Parse ISO timestamp to milliseconds since epoch."""
    if not ts:
        return 0
    # Handle numeric timestamps (Unix seconds)
    if isinstance(ts, (int, float)):
        return int(ts * 1000) if ts < 1e12 else int(ts)
    try:
        ts_str = str(ts)
        # Handle formats like "2025-01-02T12:34:56.123456+00:00" or "2025-01-02T12:34:56.123456Z"
        ts_clean = ts_str.replace("Z", "+00:00").replace("+00:00", "")
        if "+" in ts_clean:
            # Has other timezone, strip it for UTC parsing
            ts_clean = ts_clean.split("+")[0]
        dt = datetime.fromisoformat(ts_clean)
        return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)
    except (ValueError, AttributeError):
        return 0


def _extract_timestamp_from_opencode_message(msg: dict[str, Any]) -> int:
    """Extract timestamp from an OpenCode message."""
    # Try info.time.created
    info = msg.get("info") or {}
    if isinstance(info, dict):
        time_info = info.get("time") or {}
        if isinstance(time_info, dict):
            created = time_info.get("created")
            if created:
                if isinstance(created, (int, float)):
                    return int(created * 1000) if created < 1e12 else int(created)
                return _parse_iso_timestamp(str(created))

        # Try timestamp at info level
        ts = info.get("timestamp")
        if ts:
            if isinstance(ts, (int, float)):
                return int(ts * 1000) if ts < 1e12 else int(ts)
            return _parse_iso_timestamp(str(ts))

    # Try timestamp at message level
    ts = msg.get("timestamp")
    if ts:
        if isinstance(ts, (int, float)):
            return int(ts * 1000) if ts < 1e12 else int(ts)
        return _parse_iso_timestamp(str(ts))

    return 0


async def _load_timeline_file(path: Path) -> list[dict[str, Any]]:
    """Load a timeline JSONL file and add timestamp_ms (async)."""
    if not path.exists():
        return []

    # Run file I/O in thread pool to avoid blocking
    loop = asyncio.get_event_loop()
    entries = await loop.run_in_executor(None, lambda: read_ndjson_file(path, max_lines=50_000))

    result = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        ts = entry.get("ts", "")
        entry["timestamp_ms"] = _parse_iso_timestamp(ts)
        entry["source_type"] = "timeline"
        entry["source_file"] = str(path.relative_to(OUTPUTS_DIR))

        # For OPENCODE entries, also mark them as opencode source for filtering
        if entry.get("level") == "OPENCODE":
            # Extract session info from the entry
            data = entry.get("data", {})
            if isinstance(data, dict):
                entry["session_id"] = data.get("sessionID") or data.get("exec") or entry.get("exec")
                # Build parts array from the data.part if available
                part = data.get("part")
                if part:
                    entry["parts"] = [part] if isinstance(part, dict) else part
                entry["info"] = {
                    "sessionID": data.get("sessionID") or entry.get("exec"),
                    "timestamp": data.get("timestamp"),
                }

        result.append(entry)
    return result


async def _load_opencode_file(path: Path) -> list[dict[str, Any]]:
    """Load an OpenCode messages JSON file and extract events (async)."""
    if not path.exists():
        return []

    # Run file I/O in thread pool to avoid blocking
    loop = asyncio.get_event_loop()
    try:
        data = await loop.run_in_executor(None, lambda: path.read_text(encoding="utf-8"))
        data = json.loads(data)
    except (OSError, json.JSONDecodeError):
        return []

    events = []

    # Handle canonical format with sessions
    if isinstance(data, dict):
        sessions = data.get("sessions", {})
        if isinstance(sessions, dict):
            for session_id, session_data in sessions.items():
                if not isinstance(session_data, dict):
                    continue
                messages = session_data.get("messages", [])
                if isinstance(messages, list):
                    for msg in messages:
                        if isinstance(msg, dict):
                            ts = _extract_timestamp_from_opencode_message(msg)
                            msg["timestamp_ms"] = ts
                            msg["source_type"] = "opencode"
                            msg["source_file"] = str(path.relative_to(OUTPUTS_DIR))
                            msg["session_id"] = session_id
                            msg["level"] = "OPENCODE"  # Mark as OpenCode level for filtering
                            events.append(msg)

    # Handle legacy format (list of sessions/messages)
    elif isinstance(data, list):
        for item in data:
            # Skip non-dict items
            if not isinstance(item, dict):
                continue
            # Check if this is a session wrapper with messages
            if "messages" in item and isinstance(item.get("messages"), list):
                # Extract session info
                session_id = item.get("session_id", "unknown")
                # Unwrap and process each message
                for msg in item.get("messages", []):
                    if isinstance(msg, dict):
                        ts = _extract_timestamp_from_opencode_message(msg)
                        msg["timestamp_ms"] = ts
                        msg["source_type"] = "opencode"
                        msg["source_file"] = str(path.relative_to(OUTPUTS_DIR))
                        msg["session_id"] = session_id
                        msg["level"] = "OPENCODE"  # Mark as OpenCode level for filtering
                        # Preserve parts if present
                        if "parts" not in msg and "text" in item:
                            msg["parts"] = [{"type": "text", "text": item.get("text", "")}]
                        events.append(msg)
            else:
                # Direct message format
                ts = _extract_timestamp_from_opencode_message(item)
                item["timestamp_ms"] = ts
                item["source_type"] = "opencode"
                item["source_file"] = str(path.relative_to(OUTPUTS_DIR))
                item["level"] = "OPENCODE"  # Mark as OpenCode level for filtering
                events.append(item)

    return events


async def _load_alerts_file(path: Path) -> list[dict[str, Any]]:
    """Load alerts NDJSON file and add timestamp_ms (async)."""
    if not path.exists():
        return []

    # Run file I/O in thread pool to avoid blocking
    loop = asyncio.get_event_loop()
    entries = await loop.run_in_executor(None, lambda: read_ndjson_file(path, max_lines=10_000))

    result = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        # Alert entries have 'timestamp' as Unix timestamp (float) or ISO string
        ts = entry.get("timestamp") or entry.get("time", 0)
        entry["timestamp_ms"] = _parse_iso_timestamp(ts)
        entry["source_type"] = "alert"
        entry["source_file"] = str(path.relative_to(OUTPUTS_DIR))
        result.append(entry)
    return result


async def load_replay(run_id: str | None = None, path_override: str | None = None) -> dict[str, Any]:
    """Load all events for a replay and return metadata with sorted timeline.

    Args:
        run_id: The run ID to load (uses .current_run if None)
        path_override: Direct path to run directory (overrides run_id)

    Returns:
        Dict with replay metadata and sorted events
    """
    if path_override:
        run_path = Path(path_override)
        if not run_path.is_absolute():
            run_path = OUTPUTS_DIR / run_path
        run_id = run_path.name
    elif run_id:
        run_path = OUTPUTS_DIR / run_id
    else:
        current = OUTPUTS_DIR / ".current_run"
        if current.exists():
            # Run file I/O in thread pool
            loop = asyncio.get_event_loop()
            run_id = await loop.run_in_executor(None, lambda: current.read_text().strip())
            run_path = OUTPUTS_DIR / run_id
        else:
            return {"error": "No run_id provided and no .current_run file found"}

    # Check existence async
    loop = asyncio.get_event_loop()
    exists = await loop.run_in_executor(None, lambda: run_path.exists())
    if not exists:
        return {"error": f"Run directory not found: {run_path}"}

    # Load all files concurrently
    load_tasks = []
    for rel_path in _TIMELINE_PATHS:
        file_path = run_path / rel_path
        file_exists = await loop.run_in_executor(None, lambda: file_path.exists())
        if file_exists:
            if file_path.suffix == ".jsonl":
                load_tasks.append(_load_timeline_file(file_path))
            elif file_path.suffix == ".json":
                load_tasks.append(_load_opencode_file(file_path))

    # Load alerts
    alerts_path = run_path / _ALERTS_PATH
    alerts_exists = await loop.run_in_executor(None, lambda: alerts_path.exists())
    if alerts_exists:
        load_tasks.append(_load_alerts_file(alerts_path))

    # Wait for all files to load concurrently
    all_events_lists = await asyncio.gather(*load_tasks, return_exceptions=True)

    all_events = []
    for events in all_events_lists:
        if isinstance(events, Exception):
            logger.warning("Error loading file: %s", events)
            continue
        if isinstance(events, list):
            all_events.extend(events)

    # Sort by timestamp
    all_events.sort(key=lambda e: e.get("timestamp_ms", 0))

    if not all_events:
        return {
            "run_id": run_id,
            "path": str(run_path),
            "error": "No events found in run directory",
        }

    timestamps = [e.get("timestamp_ms", 0) for e in all_events if e.get("timestamp_ms")]
    if not timestamps:
        return {
            "run_id": run_id,
            "path": str(run_path),
            "error": "No valid timestamps found in events",
        }

    start_time_ms = min(ts for ts in timestamps if ts > 0)
    end_time_ms = max(ts for ts in timestamps if ts > 0)
    duration_ms = end_time_ms - start_time_ms

    # Create event index for efficient range queries
    # Store events with their position in the sorted array
    for i, event in enumerate(all_events):
        event["_index"] = i

    return {
        "run_id": run_id,
        "path": str(run_path),
        "start_time_ms": start_time_ms,
        "end_time_ms": end_time_ms,
        "duration_ms": duration_ms,
        "event_count": len(all_events),
        "events": all_events,
    }


async def get_events_in_range(
    run_id: str,
    start_ms: int,
    end_ms: int,
    path_override: str | None = None,
) -> dict[str, Any]:
    """Get events within a time range.

    Args:
        run_id: The run ID
        start_ms: Start time in milliseconds since epoch
        end_ms: End time in milliseconds since epoch
        path_override: Direct path to run directory (overrides run_id)

    Returns:
        Dict with events in the range
    """
    replay_data = await load_replay(run_id, path_override)
    if "error" in replay_data:
        return replay_data

    all_events = replay_data.get("events", [])
    filtered = [
        e for e in all_events
        if start_ms <= e.get("timestamp_ms", 0) <= end_ms
    ]

    return {
        "run_id": run_id,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "count": len(filtered),
        "events": filtered,
    }


async def list_available_runs(outputs_dir: str | None = None) -> list[dict[str, Any]]:
    """List all available run directories in outputs folder.

    Returns:
        List of run info dicts with run_id, path, created time
    """
    base = Path(outputs_dir or OUTPUTS_DIR)

    # Run file I/O in thread pool
    loop = asyncio.get_event_loop()
    exists = await loop.run_in_executor(None, lambda: base.exists())
    if not exists:
        return []

    # Read current run file
    current_run = None
    current_file = base / ".current_run"
    current_exists = await loop.run_in_executor(None, lambda: current_file.exists())
    if current_exists:
        current_run = await loop.run_in_executor(None, lambda: current_file.read_text().strip())

    # List directory entries
    def list_entries():
        return list(base.iterdir())

    entries = await loop.run_in_executor(None, list_entries)
    runs = []

    for entry in entries:
        if not entry.is_dir() or entry.name.startswith("."):
            continue

        # Check if this looks like a run directory
        # Has at least one of the expected subdirectories or files
        def check_logs():
            for check_path in ["coder56", "defender", "benign_agent", "slips"]:
                if (entry / check_path).exists():
                    return True
            return False

        has_logs = await loop.run_in_executor(None, check_logs)

        if not has_logs:
            continue

        def get_stat():
            return entry.stat()

        stat = await loop.run_in_executor(None, get_stat)
        runs.append({
            "run_id": entry.name,
            "path": str(entry),
            "is_current": entry.name == current_run,
            "created": datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc).isoformat(),
        })

    # Sort by creation time (newest first)
    runs.sort(key=lambda r: r["created"], reverse=True)
    return runs


async def close_all() -> None:
    """Cleanup function (no-op for file-based replay)."""
    return None
